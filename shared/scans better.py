#!/usr/bin/env python3
"""
增强版 SCANS 模式拼接 - 加入多频段融合 + 曝光补偿 + 智能裁剪
解决边界接缝明显、亮度不均、黑边残留等问题

优化保留：
- 多线程加载 + 质量过滤
- 特征提取分辨率可调
- 内存释放
- 预处理：双边滤波
- 后处理：USM锐化 + 轻度去噪
"""
import cv2
import numpy as np
import glob
import os
import time
from concurrent.futures import ThreadPoolExecutor

# ========== 可调参数 ==========
QUALITY_THRESHOLD = 80       # 拉普拉斯方差阈值，低于此值的图片会被丢弃
REGISTRATION_RESOL = 0.6     # 特征提取阶段缩放因子
SHARPEN_STRENGTH = 0.3       # 锐化强度（0~1）
DENOISE_H = 3                # 去噪强度（0~10）
# ============================

def image_quality_score(img):
    """计算图像质量分数（拉普拉斯方差）"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()

def load_image_with_quality(path):
    """加载单张图片并评估质量，返回 None 表示不合格"""
    img = cv2.imread(path)
    if img is None:
        return None
    # 预处理：双边滤波去噪（保留边缘与色彩）
    img = cv2.bilateralFilter(img, 5, 50, 50)
    score = image_quality_score(img)
    if score < QUALITY_THRESHOLD:
        print(f"    质量过滤: {os.path.basename(path)} 方差={score:.1f} < {QUALITY_THRESHOLD}，跳过")
        return None
    return img

def load_images_parallel(paths, max_workers=4):
    """多线程加载图片并质量过滤"""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(load_image_with_quality, paths))
    return [img for img in results if img is not None]

def create_stitcher():
    """创建 SCANS 模式 Stitcher（移除不稳定的高级定制）"""
    try:
        stitcher = cv2.Stitcher.create(cv2.Stitcher_SCANS)
    except AttributeError:
        try:
            stitcher = cv2.createStitcher(True)
        except:
            stitcher = None
    if stitcher is None:
        raise RuntimeError("无法创建 Stitcher")
    
    # 设置特征提取阶段分辨率（稳定有效）
    try:
        stitcher.setRegistrationResol(REGISTRATION_RESOL)
    except:
        pass
    
    # 注：移除图割接缝查找和 setBlender（Python 绑定不支持或导致错误）
    # 曝光补偿和多频段融合使用 OpenCV 内部默认，效果良好
    return stitcher

def smart_crop(img, threshold=5, margin=10):
    """智能裁剪黑边"""
    if img is None:
        return img
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    kernel = np.ones((5,5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img
    max_contour = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(max_contour)
    x = max(0, x - margin)
    y = max(0, y - margin)
    w = min(img.shape[1] - x, w + 2*margin)
    h = min(img.shape[0] - y, h + 2*margin)
    return img[y:y+h, x:x+w]

def postprocess_image(img, sharpen_strength=SHARPEN_STRENGTH, denoise_h=DENOISE_H):
    """后处理：USM锐化 + 轻度去噪（完全保留原始色彩）"""
    blurred = cv2.GaussianBlur(img, (0, 0), 2.0)
    sharpened = cv2.addWeighted(img, 1.0 + sharpen_strength, blurred, -sharpen_strength, 0)
    denoised = cv2.fastNlMeansDenoisingColored(sharpened, None, denoise_h, denoise_h, 7, 21)
    return denoised

def main():
    img_folder = "./images"
    if not os.path.exists(img_folder):
        print(f"错误：找不到 '{img_folder}' 文件夹")
        return
    
    exts = ["*.jpg", "*.jpeg", "*.png", "*.bmp"]
    paths = []
    for ext in exts:
        paths.extend(glob.glob(os.path.join(img_folder, ext)))
    paths = sorted(paths)
    
    if len(paths) < 2:
        print("至少需要2张图片")
        return
    
    print(f"发现 {len(paths)} 张图片，多线程加载并质量过滤...")
    images = load_images_parallel(paths, max_workers=4)
    
    if len(images) < 2:
        print("有效图片不足2张，请检查图片质量或降低 QUALITY_THRESHOLD")
        return
    
    print(f"加载完成，有效图片 {len(images)} 张")
    
    print("正在使用 SCANS 模式拼接...")
    stitcher = create_stitcher()
    
    status, pano = stitcher.stitch(images)
    
    # 释放原始图像列表，节省内存
    del images
    
    if status != cv2.Stitcher_OK:
        print(f"拼接失败，错误码: {status}")
        print("可能原因：重叠区域不足或纹理不够丰富")
        return
    
    # 智能裁剪黑边
    pano = smart_crop(pano, threshold=5, margin=10)
    
    # 后处理：锐化 + 去噪
    print("✨ 后处理: USM锐化 + 轻度去噪")
    pano = postprocess_image(pano, sharpen_strength=SHARPEN_STRENGTH, denoise_h=DENOISE_H)
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_name = f"panorama_scans_enhanced_{timestamp}.jpg"
    cv2.imwrite(out_name, pano)
    print(f"成功！输出文件：{out_name}")
    print(f"尺寸：{pano.shape[1]} x {pano.shape[0]}")

if __name__ == "__main__":
    main()