#!/usr/bin/env python3
"""Sequential pairwise panorama engine derived from the shared prototype."""
from __future__ import annotations

from typing import List, Tuple

from app.geometry.cpu_geometry import CpuGeometryEngine
from app.stitch_engine.base import StitchEngine
from app.stitch_engine.common import (
    DEFAULT_MAX_IMAGE_WIDTH,
    crop_nonzero_area,
    load_images,
    postprocess_image,
    save_result_image,
    stitch_two_images_with_orb,
)
from app.stitch_engine.opencv_engine import OpenCVStitchEngine
from app.utils.log import log_event


class SequentialPanoEngine(StitchEngine):
    requested_name = "sequential"
    actual_name = "sequential_orb"
    mode_tag = "sequential_pairwise_orb"

    def __init__(
        self,
        geometry_engine=None,
        fallback: OpenCVStitchEngine | None = None,
        *,
        max_image_width: int = DEFAULT_MAX_IMAGE_WIDTH,
    ) -> None:
        self.geometry_engine = geometry_engine or CpuGeometryEngine()
        self.fallback = fallback or OpenCVStitchEngine(geometry_engine=self.geometry_engine)
        self.max_image_width = int(max_image_width or DEFAULT_MAX_IMAGE_WIDTH)
        log_event(
            "stitch",
            "requested=sequential actual=sequential_orb fallback_ready=true",
        )

    def _stitch_sequence(self, images, cv2, auto_crop: bool):
        current = images[0]
        total = len(images)
        for index, next_image in enumerate(images[1:], start=2):
            crop_step = auto_crop or index < total
            ok, result = stitch_two_images_with_orb(
                current,
                next_image,
                cv2,
                self.geometry_engine,
                auto_crop=crop_step,
            )
            if not ok:
                return False, f"pairwise step {index - 1}->{index} failed: {result}"
            current = result
        if auto_crop:
            current = crop_nonzero_area(current, cv2)
        return True, postprocess_image(current, cv2)

    def stitch(self, image_paths: List[str], output_path: str, auto_crop: bool = False) -> Tuple[bool, str]:
        try:
            import cv2
        except Exception as exc:
            return False, f"opencv unavailable: {exc}"
        if not isinstance(image_paths, list) or len(image_paths) < 2:
            return False, "need at least two images"

        images, error = load_images(
            image_paths,
            cv2,
            max_width=self.max_image_width,
            preprocess=True,
        )
        if not images:
            return False, error or "failed to load images"

        ok, result = self._stitch_sequence(images, cv2, auto_crop=auto_crop)
        if ok:
            saved = save_result_image(output_path, result, cv2)
            return (True, "ok") if saved else (False, "failed to save result")

        fallback_ok, fallback_msg = self.fallback.stitch(image_paths, output_path, auto_crop=auto_crop)
        if fallback_ok:
            return True, fallback_msg
        return False, f"{result}; fallback: {fallback_msg}"

    def status(self) -> dict:
        info = super().status()
        info.update(
            {
                "actual": self.actual_name,
                "mode_tag": self.mode_tag,
                "geometry": self.geometry_engine.status(),
                "fallback_engine": self.fallback.status(),
                "max_image_width": self.max_image_width,
                "preprocess": "bilateral_filter",
                "postprocess": "usm+denoise",
                "pairwise_orb": True,
            }
        )
        return info
