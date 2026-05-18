#!/usr/bin/env python3
"""
优化版全景拼接脚本 - 针对 RK3588 优化
- 智能分辨率缩放
- ORB 特征点数量调优
- 详细计时信息
- 图像预处理：双边滤波（保持色彩）
- 改进 ORB 回退模式：多频段融合
- 后处理：USM 锐化 + 轻度去噪
- 内存及时释放
- 自动从 ./images 文件夹读取图片
"""
import glob
import os
import sys
import time
import argparse

import cv2
import numpy as np


# ============ 配置参数 ============
MAX_IMAGE_WIDTH = 1920      # 输入图片最大宽度（超过会缩放）
ORB_FEATURES = 2000         # ORB 特征点数量
MATCH_RATIO = 0.9          # 特征匹配比例阈值
MIN_GOOD_MATCHES = 10       # 最少匹配点数量


def log_time(start_time, message):
    """打印耗时日志"""
    elapsed = time.time() - start_time
    print(f"[TIMING] {message}: {elapsed:.2f}s")
    return time.time()


def crop_nonzero_area(image):
    """裁剪黑边"""
    if image is None or getattr(image, "size", 0) == 0:
        return image

    if len(image.shape) == 2:
        gray = image
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    mask = gray > 8
    if not mask.any():
        return image

    height, width = mask.shape
    min_pixels_per_row = max(3, width // 100)
    min_pixels_per_col = max(3, height // 100)

    valid_rows = np.where(mask.sum(axis=1) > min_pixels_per_row)[0]
    valid_cols = np.where(mask.sum(axis=0) > min_pixels_per_col)[0]

    if valid_rows.size == 0 or valid_cols.size == 0:
        valid_rows = np.where(mask.any(axis=1))[0]
        valid_cols = np.where(mask.any(axis=0))[0]
        if valid_rows.size == 0 or valid_cols.size == 0:
            return image

    y1 = int(valid_rows[0])
    y2 = int(valid_rows[-1]) + 1
    x1 = int(valid_cols[0])
    x2 = int(valid_cols[-1]) + 1

    cropped = image[y1:y2, x1:x2]
    if getattr(cropped, "size", 0) == 0:
        return image

    return cropped


def resize_image_if_needed(image, max_width=MAX_IMAGE_WIDTH):
    """智能缩放图片"""
    h, w = image.shape[:2]
    if w <= max_width:
        return image, 1.0
    
    scale = max_width / w
    new_w = int(w * scale)
    new_h = int(h * scale)
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    print(f"    缩放: {w}x{h} -> {new_w}x{new_h} (scale={scale:.2f})")
    return resized, scale


def preprocess_image(img):
    """预处理：双边滤波去噪（保持边缘与色彩）"""
    # 双边滤波 (d=5, sigmaColor=50, sigmaSpace=50) 轻度去噪
    img = cv2.bilateralFilter(img, 5, 50, 50)
    return img


def postprocess_image(img, sharpen_strength=0.3, denoise_h=3):
    """
    后处理：USM 锐化 + 轻度非局部均值去噪
    sharpen_strength: 锐化强度（0~1），默认0.3
    denoise_h: 去噪强度（0~10），默认3（很弱，仅平滑微小噪声）
    """
    # USM 锐化
    blurred = cv2.GaussianBlur(img, (0, 0), 2.0)
    sharpened = cv2.addWeighted(img, 1.0 + sharpen_strength, blurred, -sharpen_strength, 0)
    # 轻度去噪（保持原色彩）
    denoised = cv2.fastNlMeansDenoisingColored(sharpened, None, denoise_h, denoise_h, 7, 21)
    return denoised


def create_stitcher():
    """创建 OpenCV Stitcher 对象"""
    stitcher_create = getattr(cv2, "Stitcher_create", None)
    if stitcher_create is not None:
        mode = getattr(cv2, "Stitcher_PANORAMA", None)
        return stitcher_create(mode) if mode is not None else stitcher_create()

    create_stitcher_fn = getattr(cv2, "createStitcher", None)
    if create_stitcher_fn is not None:
        return create_stitcher_fn()

    return None


def stitch_two_images_with_orb(img1, img2, auto_crop=True):
    """使用 ORB 特征匹配拼接两张图片（多频段融合）"""
    timer = time.time()
    
    gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
    timer = log_time(timer, "  转灰度图")

    orb = cv2.ORB_create(nfeatures=ORB_FEATURES)
    kp1, des1 = orb.detectAndCompute(gray1, None)
    kp2, des2 = orb.detectAndCompute(gray2, None)
    timer = log_time(timer, f"  ORB特征提取 (img1:{len(kp1)}, img2:{len(kp2)})")

    if des1 is None or des2 is None or len(kp1) < 8 or len(kp2) < 8:
        return False, "not enough feature points"

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    raw_matches = matcher.knnMatch(des1, des2, k=2)

    good_matches = []
    for pair in raw_matches:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < MATCH_RATIO * n.distance:
            good_matches.append(m)

    timer = log_time(timer, f"  特征匹配 (good:{len(good_matches)})")

    if len(good_matches) < MIN_GOOD_MATCHES:
        return False, f"not enough matched points (only {len(good_matches)})"

    src_pts = np.float32([kp2[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp1[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)

    if homography is None or mask is None:
        return False, "homography estimation failed"
    
    timer = log_time(timer, "  单应矩阵估计")

    h1, w1 = img1.shape[:2]
    h2, w2 = img2.shape[:2]
    img1_corners = np.float32([[0, 0], [w1, 0], [w1, h1], [0, h1]]).reshape(-1, 1, 2)
    img2_corners = np.float32([[0, 0], [w2, 0], [w2, h2], [0, h2]]).reshape(-1, 1, 2)
    warped_img2_corners = cv2.perspectiveTransform(img2_corners, homography)
    all_corners = np.concatenate((img1_corners, warped_img2_corners), axis=0)

    [x_min, y_min] = np.int32(all_corners.min(axis=0).ravel() - 0.5)
    [x_max, y_max] = np.int32(all_corners.max(axis=0).ravel() + 0.5)

    offset_x = -x_min
    offset_y = -y_min
    translation = np.array([
        [1, 0, offset_x],
        [0, 1, offset_y],
        [0, 0, 1],
    ])

    canvas_w = max(1, x_max - x_min)
    canvas_h = max(1, y_max - y_min)
    warped_img2 = cv2.warpPerspective(img2, translation.dot(homography), (canvas_w, canvas_h))
    timer = log_time(timer, f"  透视变换 (canvas: {canvas_w}x{canvas_h})")

    # 多频段融合
    mask1 = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
    y1, y2 = offset_y, offset_y + h1
    x1, x2 = offset_x, offset_x + w1
    y2 = min(y2, canvas_h)
    x2 = min(x2, canvas_w)
    mask1[y1:y2, x1:x2] = 255

    mask2 = cv2.warpPerspective(np.ones((h2, w2), dtype=np.uint8)*255, translation.dot(homography), (canvas_w, canvas_h))

    blender = cv2.detail_MultiBandBlender()
    blender.setNumBands(5)
    blender.prepare((0, 0, canvas_w, canvas_h))

    blender.feed(img1, mask1, (offset_x, offset_y))
    blender.feed(warped_img2, mask2, (0, 0))

    dst = np.zeros((canvas_h, canvas_w, 3), dtype=np.float32)
    dst_mask = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
    blender.blend(dst, dst_mask)

    result = np.clip(dst, 0, 255).astype(np.uint8)
    timer = log_time(timer, "  多频段融合")

    if auto_crop:
        result = crop_nonzero_area(result)
        if result.size == 0:
            return False, "empty stitch result"

    return True, result


def load_images(image_paths, max_width=MAX_IMAGE_WIDTH):
    """加载并智能缩放图片，应用预处理（双边滤波）"""
    images = []
    for index, path in enumerate(image_paths, start=1):
        timer = time.time()
        image = cv2.imread(path)
        if image is None:
            print(f"❌ 无法读取图片 {index}: {path}")
            return None
        
        original_shape = image.shape
        image, scale = resize_image_if_needed(image, max_width)
        
        # 预处理：双边滤波去噪
        print(f"    预处理: 双边滤波去噪")
        image = preprocess_image(image)
        
        print(f"[{index}] {path}")
        print(f"    原始尺寸: {original_shape[1]}x{original_shape[0]}")
        if scale < 1.0:
            print(f"    处理尺寸: {image.shape[1]}x{image.shape[0]}")
        
        images.append(image)
        log_time(timer, f"  加载图片{index}")
    
    return images


def save_result(image, output_path, auto_crop=True, enhance=True):
    """保存拼接结果，可选后处理（锐化+去噪）"""
    timer = time.time()
    
    original_shape = image.shape if image is not None else None
    if auto_crop:
        image = crop_nonzero_area(image)
        if image is None or image.size == 0:
            print("❌ 结果图像为空")
            return False

        if original_shape is not None and tuple(image.shape[:2]) != tuple(original_shape[:2]):
            print(
                f"✂️  裁剪黑边: "
                f"{original_shape[1]}x{original_shape[0]} -> {image.shape[1]}x{image.shape[0]}"
            )
        else:
            print("✂️  裁剪黑边: 无明显黑边")
    else:
        print("✂️  自动裁切: 已关闭")

    # 后处理：锐化 + 轻度去噪（保持色彩）
    if enhance:
        print("✨ 后处理: USM锐化 + 轻度去噪")
        image = postprocess_image(image, sharpen_strength=0.3, denoise_h=3)

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    ok = cv2.imwrite(output_path, image)
    if ok:
        file_size = os.path.getsize(output_path) / (1024 * 1024)
        print(f"✅ 拼接成功: {output_path} ({file_size:.2f}MB)")
    else:
        print(f"❌ 保存失败: {output_path}")
    
    log_time(timer, "保存结果")
    return ok


def stitch_image_files(image_paths, output_path, auto_crop=True, enhance=True):
    """主拼接函数（内存释放）"""
    total_timer = time.time()
    
    if len(image_paths) < 2:
        print("❌ 至少需要两张图片")
        return False

    print("\n" + "="*60)
    print("🔧 开始拼接...")
    print("="*60)

    images = load_images(image_paths)
    if not images:
        return False

    attempt_orders = [images]
    if len(images) > 1:
        reversed_images = list(reversed(images))
        attempt_orders.append(reversed_images)

    # 尝试使用 OpenCV Stitcher
    if create_stitcher() is not None:
        print("\n📸 尝试使用 OpenCV Stitcher...")
        for attempt_index, ordered_images in enumerate(attempt_orders, start=1):
            timer = time.time()
            stitcher = create_stitcher()
            status, panorama = stitcher.stitch(ordered_images)
            log_time(timer, f"OpenCV Stitcher 尝试 {attempt_index} (status={status})")
            
            if status == 0 and panorama is not None and getattr(panorama, "size", 0) > 0:
                print(f"✅ OpenCV Stitcher 成功 (尝试 {attempt_index})")
                success = save_result(panorama, output_path, auto_crop=auto_crop, enhance=enhance)
                del images
                log_time(total_timer, "总耗时")
                return success

    # 如果是两张图片，回退到 ORB 方法
    if len(images) == 2:
        print("\n🔄 OpenCV Stitcher 失败，使用 ORB 特征匹配（多频段融合）...")
        ok, result = stitch_two_images_with_orb(images[0], images[1], auto_crop=auto_crop)
        if not ok:
            print(f"❌ ORB 拼接失败: {result}")
            log_time(total_timer, "总耗时")
            return False
        
        print("✅ ORB 拼接成功")
        success = save_result(result, output_path, auto_crop=auto_crop, enhance=enhance)
        del images
        log_time(total_timer, "总耗时")
        return success

    print("❌ 多图拼接失败")
    del images
    log_time(total_timer, "总耗时")
    return False


def discover_input_images(image_args=None):
    """自动发现输入图片：优先使用命令行参数，否则从 ./images 文件夹读取"""
    if image_args:
        return image_args

    img_folder = "./images"
    if os.path.isdir(img_folder):
        exts = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp", "*.tif", "*.tiff")
        paths = []
        for ext in exts:
            paths.extend(glob.glob(os.path.join(img_folder, ext)))
        if paths:
            return sorted(paths)
        else:
            print(f"警告：文件夹 '{img_folder}' 中没有找到图片，将尝试从当前目录查找。")
    # 回退：从当前目录查找常见图片
    patterns = (
        "img*.jpg",
        "img*.jpeg",
        "img*.png",
        "img*.bmp",
        "img*.webp",
        "img*.tif",
        "img*.tiff",
    )
    results = []
    seen = set()
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            full_path = os.path.abspath(path)
            if full_path in seen:
                continue
            seen.add(full_path)
            results.append(path)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RK3588 全景拼接工具（预处理：双边滤波，后处理：锐化+去噪）")
    parser.add_argument("images", nargs="*", help="待拼接图片路径（至少两张）")
    parser.add_argument("--output", default="", help="输出文件路径")
    parser.add_argument("--auto-crop", action="store_true", help="启用自动黑边裁切")
    parser.add_argument("--no-auto-crop", action="store_true", help="关闭自动黑边裁切")
    parser.add_argument("--no-enhance", action="store_true", help="关闭后处理（锐化+去噪）")
    args = parser.parse_args()

    auto_crop = True
    if args.auto_crop:
        auto_crop = True
    if args.no_auto_crop:
        auto_crop = False

    enhance = not args.no_enhance   # 默认开启后处理

    print("=" * 60)
    print("📷 RK3588 优化版全景拼接工具（双边滤波+锐化+去噪）")
    print("=" * 60)
    print(f"配置: MAX_WIDTH={MAX_IMAGE_WIDTH}, ORB_FEATURES={ORB_FEATURES}")
    print(f"OpenCV 版本: {cv2.__version__}")
    print(f"自动裁切黑边: {'开启' if auto_crop else '关闭'}")
    print(f"后处理（锐化+去噪）: {'开启' if enhance else '关闭'}")
    print("=" * 60)
    
    image_paths = discover_input_images(args.images)
    if len(image_paths) < 2:
        print("\n用法:")
        print("  python3 stitch_demo.py img1.jpg img2.jpg [img3.jpg ...] [--output result.jpg]")
        print("  或将文件命名为 img1.jpg, img2.jpg... 放在当前目录")
        print("  或创建 ./images 文件夹并将图片放入其中（推荐）")
        sys.exit(1)

    print("\n📂 输入图片:")
    for index, path in enumerate(image_paths, start=1):
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"  {index}. {path} ({size_mb:.2f}MB)")

    output_file = args.output.strip()
    if not output_file:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = f"stitched_{timestamp}.jpg"
    
    success = stitch_image_files(image_paths, output_file, auto_crop=auto_crop, enhance=enhance)

    print("\n" + "="*60)
    if success:
        print("✅ 任务完成")
    else:
        print("❌ 拼接失败，请检查:")
        print("   1. 图片之间是否有足够的重叠区域（建议30%以上）")
        print("   2. 图片顺序是否正确（从左到右或从右到左）")
        print("   3. 图片光照是否一致")
    print("="*60)