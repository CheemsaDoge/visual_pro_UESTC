#!/usr/bin/env python3
"""Enhanced OpenCV SCANS stitch engine derived from the shared prototype."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple

from app.stitch_engine.base import StitchEngine
from app.stitch_engine.common import (
    DEFAULT_DENOISE_H,
    DEFAULT_SHARPEN_STRENGTH,
    create_stitcher,
    image_quality_score,
    load_and_prepare_image,
    postprocess_image,
    save_result_image,
    smart_crop,
)


class ScansStitchEngine(StitchEngine):
    requested_name = "scans"
    actual_name = "opencv_scans"
    mode_tag = "opencv_scans_enhanced"

    def __init__(
        self,
        *,
        quality_threshold: float = 80.0,
        registration_resol: float = 0.6,
        max_workers: int = 4,
        max_image_width: int = 0,
        sharpen_strength: float = DEFAULT_SHARPEN_STRENGTH,
        denoise_h: int = DEFAULT_DENOISE_H,
    ) -> None:
        self.quality_threshold = float(quality_threshold)
        self.registration_resol = float(registration_resol)
        self.max_workers = max(1, int(max_workers or 1))
        self.max_image_width = int(max_image_width or 0)
        self.sharpen_strength = float(sharpen_strength)
        self.denoise_h = int(denoise_h)

    @staticmethod
    def _create_stitcher(cv2):
        return create_stitcher(cv2, mode="scans")

    def _load_image_with_quality(self, path: str, cv2):
        try:
            image = load_and_prepare_image(
                path,
                cv2,
                max_width=self.max_image_width,
                preprocess=True,
            )
        except ValueError:
            return None
        if image_quality_score(image, cv2) < self.quality_threshold:
            return None
        return image

    def stitch(self, image_paths: List[str], output_path: str, auto_crop: bool = False) -> Tuple[bool, str]:
        try:
            import cv2
        except Exception as exc:
            return False, f"opencv unavailable: {exc}"
        if not isinstance(image_paths, list) or len(image_paths) < 2:
            return False, "need at least two images"

        max_workers = min(self.max_workers, len(image_paths))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            images = list(executor.map(lambda path: self._load_image_with_quality(path, cv2), image_paths))
        images = [image for image in images if image is not None]
        if len(images) < 2:
            return False, "not enough valid images after quality filter"

        stitcher = self._create_stitcher(cv2)
        if stitcher is None:
            return False, "opencv stitcher unavailable for scans mode"
        try:
            stitcher.setRegistrationResol(self.registration_resol)
        except Exception:
            pass

        try:
            status, panorama = stitcher.stitch(images)
        except Exception as exc:
            return False, f"opencv scans stitch failed: {exc}"
        if status != getattr(cv2, "Stitcher_OK", 0) or panorama is None or getattr(panorama, "size", 0) == 0:
            return False, f"opencv scans stitch failed ({status})"

        if auto_crop:
            panorama = smart_crop(panorama, cv2, threshold=5, margin=10)
        panorama = postprocess_image(
            panorama,
            cv2,
            sharpen_strength=self.sharpen_strength,
            denoise_h=self.denoise_h,
        )
        ok = save_result_image(output_path, panorama, cv2)
        return (True, "ok") if ok else (False, "failed to save result")

    def status(self) -> dict:
        info = super().status()
        try:
            import cv2

            info.update(
                {
                    "opencv": getattr(cv2, "__version__", "unknown"),
                    "quality_threshold": self.quality_threshold,
                    "registration_resol": self.registration_resol,
                    "max_image_width": self.max_image_width,
                    "postprocess": "usm+denoise",
                }
            )
        except Exception as exc:
            info.update({"available": False, "reason": f"opencv unavailable: {exc}"})
        return info
