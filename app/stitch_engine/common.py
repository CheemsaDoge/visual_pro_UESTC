#!/usr/bin/env python3
"""Common helpers shared by the modular stitch engines."""
from __future__ import annotations

import os
import time
from typing import List, Sequence, Tuple

DEFAULT_MAX_IMAGE_WIDTH = 1920
DEFAULT_ORB_FEATURES = 2000
DEFAULT_MATCH_RATIO = 0.9
DEFAULT_MIN_GOOD_MATCHES = 10
DEFAULT_SHARPEN_STRENGTH = 0.3
DEFAULT_DENOISE_H = 3


def crop_nonzero_area(image, cv2):
    import numpy as np

    if image is None or getattr(image, "size", 0) == 0:
        return image
    gray = image if len(image.shape) == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
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


def smart_crop(image, cv2, threshold: int = 5, margin: int = 10):
    import numpy as np

    if image is None or getattr(image, "size", 0) == 0:
        return image
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _ret, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return image
    x, y, w, h = cv2.boundingRect(max(contours, key=cv2.contourArea))
    x = max(0, x - margin)
    y = max(0, y - margin)
    w = min(image.shape[1] - x, w + 2 * margin)
    h = min(image.shape[0] - y, h + 2 * margin)
    return image[y:y + h, x:x + w]


def resize_image_if_needed(image, cv2, max_width: int = DEFAULT_MAX_IMAGE_WIDTH):
    max_width = int(max_width or 0)
    if max_width <= 0:
        return image, 1.0
    height, width = image.shape[:2]
    if width <= max_width:
        return image, 1.0
    scale = max_width / float(width)
    new_width = max(1, int(width * scale))
    new_height = max(1, int(height * scale))
    resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
    return resized, scale


def preprocess_image(image, cv2):
    return cv2.bilateralFilter(image, 5, 50, 50)


def postprocess_image(
    image,
    cv2,
    sharpen_strength: float = DEFAULT_SHARPEN_STRENGTH,
    denoise_h: int = DEFAULT_DENOISE_H,
):
    if image is None or getattr(image, "size", 0) == 0:
        return image
    blurred = cv2.GaussianBlur(image, (0, 0), 2.0)
    sharpened = cv2.addWeighted(image, 1.0 + sharpen_strength, blurred, -sharpen_strength, 0)
    return cv2.fastNlMeansDenoisingColored(sharpened, None, denoise_h, denoise_h, 7, 21)


def create_stitcher(cv2, mode: str = "panorama"):
    stitcher_create = getattr(cv2, "Stitcher_create", None)
    if stitcher_create is not None:
        mode_name = "Stitcher_SCANS" if mode == "scans" else "Stitcher_PANORAMA"
        mode_value = getattr(cv2, mode_name, None)
        return stitcher_create(mode_value) if mode_value is not None else stitcher_create()

    legacy_create = getattr(cv2, "createStitcher", None)
    if legacy_create is not None:
        try:
            return legacy_create(mode == "scans")
        except TypeError:
            return legacy_create()
    return None


def load_and_prepare_image(path: str, cv2, max_width: int = DEFAULT_MAX_IMAGE_WIDTH, preprocess: bool = True):
    image = cv2.imread(path)
    if image is None:
        raise ValueError(f"cannot read image: {os.path.basename(path)}")
    image, _scale = resize_image_if_needed(image, cv2, max_width=max_width)
    if preprocess:
        image = preprocess_image(image, cv2)
    return image


def load_images(
    image_paths: Sequence[str],
    cv2,
    max_width: int = DEFAULT_MAX_IMAGE_WIDTH,
    preprocess: bool = True,
) -> Tuple[List, str]:
    images = []
    for index, path in enumerate(image_paths, start=1):
        try:
            image = load_and_prepare_image(path, cv2, max_width=max_width, preprocess=preprocess)
        except ValueError:
            return [], f"cannot read image {index}: {os.path.basename(path)}"
        images.append(image)
    return images, ""


def image_quality_score(image, cv2) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def save_result_image(output_path: str, image, cv2) -> bool:
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    return bool(cv2.imwrite(output_path, image))


def _blend_warped_pair(base_canvas, warped_image, mask1, mask2, cv2):
    import numpy as np

    if hasattr(cv2, "detail_MultiBandBlender"):
        try:
            blender = cv2.detail_MultiBandBlender()
            blender.setNumBands(5)
            blender.prepare((0, 0, base_canvas.shape[1], base_canvas.shape[0]))
            blender.feed(base_canvas.astype(np.int16), mask1, (0, 0))
            blender.feed(warped_image.astype(np.int16), mask2, (0, 0))
            blended = np.zeros_like(base_canvas, dtype=np.int16)
            blended_mask = np.zeros(mask1.shape, dtype=np.uint8)
            blender.blend(blended, blended_mask)
            return np.clip(blended, 0, 255).astype(np.uint8)
        except Exception:
            pass

    result = base_canvas.copy()
    warped_mask = mask2 > 0
    base_mask = mask1 > 0
    warped_only_mask = warped_mask & (~base_mask)
    overlap_mask = warped_mask & base_mask
    result[warped_only_mask] = warped_image[warped_only_mask]
    if overlap_mask.any():
        merged = (
            base_canvas[overlap_mask].astype(np.uint16)
            + warped_image[overlap_mask].astype(np.uint16)
        ) // 2
        result[overlap_mask] = merged.astype(np.uint8)
    return result


def stitch_two_images_with_orb(
    img1,
    img2,
    cv2,
    geometry_engine,
    *,
    auto_crop: bool = False,
    orb_features: int = DEFAULT_ORB_FEATURES,
    match_ratio: float = DEFAULT_MATCH_RATIO,
    min_good_matches: int = DEFAULT_MIN_GOOD_MATCHES,
    telemetry: dict | None = None,
):
    import numpy as np

    started = time.perf_counter()
    telemetry = telemetry if telemetry is not None else {}
    telemetry.update({
        "algorithm": "ORB + BFMatcher(Hamming) + Lowe ratio + RANSAC homography",
        "parameters": {
            "orb_features": orb_features,
            "match_ratio": match_ratio,
            "min_good_matches": min_good_matches,
            "ransac_reproj_threshold": 5.0,
        },
    })
    gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=orb_features)
    kp1, des1 = orb.detectAndCompute(gray1, None)
    kp2, des2 = orb.detectAndCompute(gray2, None)
    telemetry["feature_points"] = {"left": len(kp1), "right": len(kp2)}
    if des1 is None or des2 is None or len(kp1) < 8 or len(kp2) < 8:
        telemetry["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        return False, "not enough feature points"

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    raw_matches = matcher.knnMatch(des1, des2, k=2)
    good_matches = []
    for pair in raw_matches:
        if len(pair) < 2:
            continue
        first, second = pair
        if first.distance < match_ratio * second.distance:
            good_matches.append(first)
    telemetry["matches"] = {"raw_knn_pairs": len(raw_matches), "good_ratio_matches": len(good_matches)}
    if len(good_matches) < min_good_matches:
        telemetry["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        return False, f"not enough matched points (only {len(good_matches)})"

    src_pts = np.float32([kp2[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp1[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    telemetry["homography"] = {"inliers": int(mask.ravel().sum()) if mask is not None else 0}
    if homography is None or mask is None:
        telemetry["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        return False, "homography estimation failed"

    h1, w1 = img1.shape[:2]
    h2, w2 = img2.shape[:2]
    img1_corners = np.float32([[0, 0], [w1, 0], [w1, h1], [0, h1]]).reshape(-1, 1, 2)
    img2_corners = np.float32([[0, 0], [w2, 0], [w2, h2], [0, h2]]).reshape(-1, 1, 2)
    warped_img2_corners = cv2.perspectiveTransform(img2_corners, homography)
    all_corners = np.concatenate((img1_corners, warped_img2_corners), axis=0)
    x_min, y_min = np.int32(all_corners.min(axis=0).ravel() - 0.5)
    x_max, y_max = np.int32(all_corners.max(axis=0).ravel() + 0.5)

    offset_x = -x_min
    offset_y = -y_min
    translation = np.array(
        [
            [1, 0, offset_x],
            [0, 1, offset_y],
            [0, 0, 1],
        ],
        dtype=np.float32,
    )
    canvas_w = max(1, x_max - x_min)
    canvas_h = max(1, y_max - y_min)
    max_dim = max(w1 + w2, h1 + h2, 1) * 4
    max_area = max(1, (w1 * h1 + w2 * h2) * 12)
    if canvas_w > max_dim or canvas_h > max_dim or canvas_w * canvas_h > max_area:
        telemetry["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        return False, "homography produced unreasonable canvas"

    transform = translation.dot(homography)
    warped_img2 = geometry_engine.warp_perspective(img2, transform, (canvas_w, canvas_h))
    if warped_img2 is None or getattr(warped_img2, "size", 0) == 0:
        telemetry["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        return False, "warpPerspective failed"
    if warped_img2.shape[0] != canvas_h or warped_img2.shape[1] != canvas_w:
        telemetry["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        return False, "geometry engine returned invalid canvas"

    base_canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    mask1 = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
    base_canvas[offset_y:offset_y + h1, offset_x:offset_x + w1] = img1
    mask1[offset_y:offset_y + h1, offset_x:offset_x + w1] = 255
    mask2 = cv2.warpPerspective(
        np.full((h2, w2), 255, dtype=np.uint8),
        transform,
        (canvas_w, canvas_h),
    )

    result = _blend_warped_pair(base_canvas, warped_img2, mask1, mask2, cv2)
    if auto_crop:
        result = crop_nonzero_area(result, cv2)
        if result is None or getattr(result, "size", 0) == 0:
            telemetry["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
            return False, "empty stitch result"
    telemetry["canvas"] = {"width": int(result.shape[1]), "height": int(result.shape[0])}
    telemetry["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    return True, result
