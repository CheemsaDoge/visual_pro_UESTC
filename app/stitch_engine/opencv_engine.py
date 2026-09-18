#!/usr/bin/env python3
"""Enhanced OpenCV panorama stitch engine."""
from __future__ import annotations

from typing import List, Tuple
import time

from app.geometry.cpu_geometry import CpuGeometryEngine
from app.stitch_engine.base import StitchEngine
from app.stitch_engine.common import (
    DEFAULT_MAX_IMAGE_WIDTH,
    crop_nonzero_area,
    create_stitcher,
    load_images,
    postprocess_image,
    save_result_image,
    stitch_two_images_with_orb,
)


class OpenCVStitchEngine(StitchEngine):
    requested_name = "builtin"
    actual_name = "opencv"
    mode_tag = "opencv_panorama_enhanced"

    def __init__(self, geometry_engine=None, *, max_image_width: int = DEFAULT_MAX_IMAGE_WIDTH) -> None:
        self.geometry_engine = geometry_engine or CpuGeometryEngine()
        self.max_image_width = int(max_image_width or DEFAULT_MAX_IMAGE_WIDTH)

    @staticmethod
    def _create_stitcher(cv2):
        return create_stitcher(cv2, mode="panorama")

    def _save_panorama(self, panorama, output_path: str, auto_crop: bool, cv2) -> Tuple[bool, str]:
        started = time.perf_counter()
        if auto_crop:
            panorama = crop_nonzero_area(panorama, cv2)
        panorama = postprocess_image(panorama, cv2, geometry_engine=self.geometry_engine)
        ok = save_result_image(output_path, panorama, cv2)
        self._record_stage("postprocess_and_save", started, output_width=int(panorama.shape[1]), output_height=int(panorama.shape[0]), saved=bool(ok))
        return (True, "ok") if ok else (False, "failed to save result")

    def stitch(self, image_paths: List[str], output_path: str, auto_crop: bool = False) -> Tuple[bool, str]:
        detail = self._begin_run_detail(image_paths, auto_crop)
        detail["parameters"].update({"max_image_width": self.max_image_width, "preprocess": "bilateral_filter", "postprocess": "usm+denoise"})
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

        stitcher = self._create_stitcher(cv2)
        if stitcher is not None:
            attempt_orders = [images]
            if len(images) > 1:
                attempt_orders.append(list(reversed(images)))
            status_list = []
            for attempt_index, ordered in enumerate(attempt_orders, start=1):
                stitcher = self._create_stitcher(cv2)
                attempt_started = time.perf_counter()
                try:
                    status, panorama = stitcher.stitch(ordered)
                except Exception as exc:
                    status_list.append(f"exception:{exc}")
                    self._record_stage("opencv_panorama_attempt", attempt_started, attempt=attempt_index, order="reversed" if attempt_index > 1 else "original", error=str(exc))
                    continue
                status_list.append(status)
                self._record_stage("opencv_panorama_attempt", attempt_started, attempt=attempt_index, order="reversed" if attempt_index > 1 else "original", status=int(status))
                if status == getattr(cv2, "Stitcher_OK", 0) and panorama is not None and getattr(panorama, "size", 0) > 0:
                    return self._save_panorama(panorama, output_path, auto_crop=auto_crop, cv2=cv2)
            if len(images) != 2:
                status_text = ",".join(str(item) for item in status_list) or "unknown"
                return False, f"opencv stitch failed ({status_text})"

        if len(images) == 2:
            detail["fallback"] = {"used": True, "type": "two_image_orb", "reason": "OpenCV panorama stitcher did not produce a result"}
            orb_detail = {}
            fallback_started = time.perf_counter()
            ok, result = stitch_two_images_with_orb(
                images[0],
                images[1],
                cv2,
                self.geometry_engine,
                auto_crop=auto_crop,
                telemetry=orb_detail,
            )
            self._record_stage("orb_fallback", fallback_started, **orb_detail)
            if not ok:
                return False, result
            save_started = time.perf_counter()
            panorama = postprocess_image(result, cv2, geometry_engine=self.geometry_engine)
            saved = save_result_image(output_path, panorama, cv2)
            self._record_stage("postprocess_and_save", save_started, output_width=int(panorama.shape[1]), output_height=int(panorama.shape[0]), saved=bool(saved))
            return (True, "ok") if saved else (False, "failed to save result")

        return False, "opencv stitcher unavailable for multi-image stitching"

    def status(self) -> dict:
        info = super().status()
        try:
            import cv2

            info.update(
                {
                    "opencv": getattr(cv2, "__version__", "unknown"),
                    "stitcher": bool(getattr(cv2, "Stitcher_create", None) or getattr(cv2, "createStitcher", None)),
                    "geometry": self.geometry_engine.status(),
                    "max_image_width": self.max_image_width,
                    "preprocess": "bilateral_filter",
                    "postprocess": "usm+denoise",
                    "orb_fallback": True,
                }
            )
        except Exception as exc:
            info.update({"available": False, "reason": f"opencv unavailable: {exc}"})
        return info
