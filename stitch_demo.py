#!/usr/bin/env python3
"""
优化版全景拼接脚本 - 针对 RK3588 优化
改进点：
1. 智能分辨率缩放（降低计算量）
2. 减少 ORB 特征点（加速匹配）
3. 详细计时信息
4. 更好的错误提示
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
ORB_FEATURES = 1500         # ORB 特征点数量（从2500降到1500）
MATCH_RATIO = 0.75          # 特征匹配比例阈值
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

    # Ignore tiny bright edge noise so sparse pixels do not block border cropping.
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
    """使用 ORB 特征匹配拼接两张图片"""
    timer = time.time()
    
    gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
    timer = log_time(timer, "  转灰度图")

    # 使用优化后的特征点数量
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

    result = warped_img2.copy()
    img1_y1 = offset_y
    img1_y2 = offset_y + h1
    img1_x1 = offset_x
    img1_x2 = offset_x + w1

    if result.shape[0] < img1_y2 or result.shape[1] < img1_x2:
        return False, "canvas size is invalid"

    mask1 = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
    mask1[img1_y1:img1_y2, img1_x1:img1_x2] = 255

    result[img1_y1:img1_y2, img1_x1:img1_x2] = img1

    warped_mask = cv2.cvtColor(warped_img2, cv2.COLOR_BGR2GRAY) > 0
    base_mask = mask1 > 0
    overlap_mask = warped_mask & base_mask
    warped_only_mask = warped_mask & (~base_mask)

    result[warped_only_mask] = warped_img2[warped_only_mask]

    if overlap_mask.any():
        merged = (
            result[overlap_mask].astype(np.uint16) + warped_img2[overlap_mask].astype(np.uint16)
        ) // 2
        result[overlap_mask] = merged.astype(np.uint8)

    timer = log_time(timer, "  图像融合")

    if auto_crop:
        result = crop_nonzero_area(result)
        if result.size == 0:
            return False, "empty stitch result"

    return True, result


def load_images(image_paths, max_width=MAX_IMAGE_WIDTH):
    """加载并智能缩放图片"""
    images = []
    for index, path in enumerate(image_paths, start=1):
        timer = time.time()
        image = cv2.imread(path)
        if image is None:
            print(f"❌ 无法读取图片 {index}: {path}")
            return None
        
        original_shape = image.shape
        image, scale = resize_image_if_needed(image, max_width)
        
        print(f"[{index}] {path}")
        print(f"    原始尺寸: {original_shape[1]}x{original_shape[0]}")
        if scale < 1.0:
            print(f"    处理尺寸: {image.shape[1]}x{image.shape[0]}")
        
        images.append(image)
        log_time(timer, f"  加载图片{index}")
    
    return images


def save_result(image, output_path, auto_crop=True):
    """保存拼接结果"""
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


def stitch_image_files(image_paths, output_path, auto_crop=True):
    """主拼接函数"""
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
                success = save_result(panorama, output_path, auto_crop=auto_crop)
                log_time(total_timer, "总耗时")
                return success

    # 如果是两张图片，回退到 ORB 方法
    if len(images) == 2:
        print("\n🔄 OpenCV Stitcher 失败，使用 ORB 特征匹配...")
        ok, result = stitch_two_images_with_orb(images[0], images[1], auto_crop=auto_crop)
        if not ok:
            print(f"❌ ORB 拼接失败: {result}")
            log_time(total_timer, "总耗时")
            return False
        
        print("✅ ORB 拼接成功")
        success = save_result(result, output_path, auto_crop=auto_crop)
        log_time(total_timer, "总耗时")
        return success

    print("❌ 多图拼接失败")
    log_time(total_timer, "总耗时")
    return False


def discover_input_images(image_args=None):
    """自动发现输入图片"""
    if image_args:
        return image_args

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
    parser = argparse.ArgumentParser(description="RK3588 优化版全景拼接工具")
    parser.add_argument("images", nargs="*", help="待拼接图片路径（至少两张）")
    parser.add_argument("--output", default="", help="输出文件路径")
    parser.add_argument("--auto-crop", action="store_true", help="启用自动黑边裁切")
    parser.add_argument("--no-auto-crop", action="store_true", help="关闭自动黑边裁切")
    args = parser.parse_args()

    auto_crop = True
    if args.auto_crop:
        auto_crop = True
    if args.no_auto_crop:
        auto_crop = False

    print("=" * 60)
    print("📷 RK3588 优化版全景拼接工具")
    print("=" * 60)
    print(f"配置: MAX_WIDTH={MAX_IMAGE_WIDTH}, ORB_FEATURES={ORB_FEATURES}")
    print(f"OpenCV 版本: {cv2.__version__}")
    print(f"自动裁切黑边: {'开启' if auto_crop else '关闭'}")
    print("=" * 60)
    
    image_paths = discover_input_images(args.images)
    if len(image_paths) < 2:
        print("\n用法:")
        print("  python3 stitch_demo.py img1.jpg img2.jpg [img3.jpg ...] [--output result.jpg]")
        print("  或将文件命名为 img1.jpg, img2.jpg... 放在当前目录")
        sys.exit(1)

    print("\n📂 输入图片:")
    for index, path in enumerate(image_paths, start=1):
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"  {index}. {path} ({size_mb:.2f}MB)")

    output_file = args.output.strip()
    if not output_file:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = f"stitched_{timestamp}.jpg"
    
    success = stitch_image_files(image_paths, output_file, auto_crop=auto_crop)

    print("\n" + "="*60)
    if success:
        print("✅ 任务完成")
    else:
        print("❌ 拼接失败，请检查:")
        print("   1. 图片之间是否有足够的重叠区域（建议30%以上）")
        print("   2. 图片顺序是否正确（从左到右或从右到左）")
        print("   3. 图片光照是否一致")
    print("="*60)
