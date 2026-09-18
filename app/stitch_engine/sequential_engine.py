#!/usr/bin/env python3
"""Sequential pairwise panorama engine derived from the shared prototype."""
from __future__ import annotations

from typing import List, Tuple
import time

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
            pair_detail = {"pair": f"{index - 1}->{index}"}
            pair_started = time.perf_counter()
            ok, result = stitch_two_images_with_orb(
                current,
                next_image,
                cv2,
                self.geometry_engine,
                auto_crop=crop_step,
                telemetry=pair_detail,
            )
            self._record_stage("pairwise_orb", pair_started, **pair_detail)
            if not ok:
                return False, f"pairwise step {index - 1}->{index} failed: {result}"
            current = result
        if auto_crop:
            current = crop_nonzero_area(current, cv2)
        postprocess_detail = {}
        postprocess_started = time.perf_counter()
        current = postprocess_image(current, cv2, telemetry=postprocess_detail)
        self._record_stage("postprocess", postprocess_started, **postprocess_detail)
        return True, current

    def stitch(self, image_paths: List[str], output_path: str, auto_crop: bool = False) -> Tuple[bool, str]:
        detail = self._begin_run_detail(image_paths, auto_crop)
        detail["parameters"].update({"max_image_width": self.max_image_width, "pairwise_orb": True, "fallback_engine": self.fallback.actual_name if hasattr(self.fallback, "actual_name") else "unknown"})
        try:
            import cv2
        except Exception as exc:
            return False, f"opencv unavailable: {exc}"
        if not isinstance(image_paths, list) or len(image_paths) < 2:
            return False, "need at least two images"

        load_started = time.perf_counter()
        images, error = load_images(
            image_paths,
            cv2,
            max_width=self.max_image_width,
            preprocess=True,
        )
        if not images:
            self._record_stage("load_and_preprocess", load_started, error=error)
            return False, error or "failed to load images"
        self._record_stage("load_and_preprocess", load_started, images=[{"width": int(image.shape[1]), "height": int(image.shape[0])} for image in images])

        sequence_started = time.perf_counter()
        ok, result = self._stitch_sequence(images, cv2, auto_crop=auto_crop)
        self._record_stage("pairwise_sequence_total", sequence_started, success=bool(ok))
        if ok:
            save_started = time.perf_counter()
            saved = save_result_image(output_path, result, cv2)
            self._record_stage("save_result", save_started, output_width=int(result.shape[1]), output_height=int(result.shape[0]), saved=bool(saved))
            return (True, "ok") if saved else (False, "failed to save result")

        detail["fallback"] = {"used": True, "type": "opencv_panorama", "reason": str(result)}
        fallback_started = time.perf_counter()
        fallback_ok, fallback_msg = self.fallback.stitch(image_paths, output_path, auto_crop=auto_crop)
        self._record_stage("opencv_fallback", fallback_started, success=bool(fallback_ok), detail=self.fallback.get_last_run_detail() if hasattr(self.fallback, "get_last_run_detail") else {})
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
