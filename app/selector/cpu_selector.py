#!/usr/bin/env python3
"""Simple CPU keyframe selector based on interval, blur, and frame difference."""
from __future__ import annotations

from typing import Any, Dict

from app import config
from app.schemas import ProcessedFrame
from app.selector.base import KeyframeSelector


class CpuSelector(KeyframeSelector):
    requested_name = "cpu_basic"
    actual_name = "cpu_basic"
    mode_tag = "selector_cpu_basic"

    def __init__(
        self,
        min_interval_sec: float | None = None,
        blur_threshold: float | None = None,
        diff_threshold: float | None = None,
        diff_resize_width: int | None = None,
    ) -> None:
        self.min_interval_sec = (
            config.CPU_SELECTOR_MIN_INTERVAL_SEC if min_interval_sec is None else float(min_interval_sec)
        )
        self.blur_threshold = (
            config.CPU_SELECTOR_BLUR_THRESHOLD if blur_threshold is None else float(blur_threshold)
        )
        self.diff_threshold = (
            config.CPU_SELECTOR_DIFF_THRESHOLD if diff_threshold is None else float(diff_threshold)
        )
        self.diff_resize_width = (
            config.CPU_SELECTOR_DIFF_RESIZE_WIDTH if diff_resize_width is None else int(diff_resize_width)
        )

    @staticmethod
    def _image(obj: Any):
        if isinstance(obj, ProcessedFrame):
            return obj.bgr_image
        return getattr(obj, "bgr_image", obj)

    @staticmethod
    def _timestamp(obj: Any, context: Dict[str, Any] | None) -> float:
        if hasattr(obj, "timestamp"):
            try:
                return float(getattr(obj, "timestamp"))
            except Exception:
                pass
        if context and "now" in context:
            try:
                return float(context["now"])
            except Exception:
                pass
        import time

        return time.time()

    def _blur_score(self, image: Any) -> float:
        import cv2

        if image is None:
            return 0.0
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def _diff_score(self, image: Any, previous_image: Any) -> float:
        import cv2
        import numpy as np

        if image is None or previous_image is None:
            return 255.0
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        prev = cv2.cvtColor(previous_image, cv2.COLOR_BGR2GRAY) if len(previous_image.shape) == 3 else previous_image
        if gray.shape[:2] != prev.shape[:2]:
            width = self.diff_resize_width
            scale = width / float(max(1, gray.shape[1]))
            gray = cv2.resize(gray, (width, max(1, int(gray.shape[0] * scale))), interpolation=cv2.INTER_AREA)
            prev = cv2.resize(prev, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_AREA)
        elif gray.shape[1] > self.diff_resize_width:
            width = self.diff_resize_width
            scale = width / float(max(1, gray.shape[1]))
            size = (width, max(1, int(gray.shape[0] * scale)))
            gray = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
            prev = cv2.resize(prev, size, interpolation=cv2.INTER_AREA)
        return float(np.mean(cv2.absdiff(gray, prev)))

    def decision(self, frame_or_processed_frame: Any, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        context = context or {}
        image = self._image(frame_or_processed_frame)
        now = self._timestamp(frame_or_processed_frame, context)
        last_keep_ts = float(context.get("last_keep_ts") or 0.0)
        previous_image = context.get("last_keep_image")

        if last_keep_ts > 0 and self.min_interval_sec > 0 and (now - last_keep_ts) < self.min_interval_sec:
            return {
                "keep": False,
                "reason": "interval",
                "elapsed_sec": now - last_keep_ts,
                "min_interval_sec": self.min_interval_sec,
                "selector": self.actual_name,
                "mode_tag": self.mode_tag,
            }

        blur = self._blur_score(image)
        if blur < self.blur_threshold:
            return {
                "keep": False,
                "reason": "blur",
                "blur_score": blur,
                "blur_threshold": self.blur_threshold,
                "selector": self.actual_name,
                "mode_tag": self.mode_tag,
            }

        diff = self._diff_score(image, previous_image)
        if previous_image is not None and diff < self.diff_threshold:
            return {
                "keep": False,
                "reason": "duplicate",
                "diff_score": diff,
                "diff_threshold": self.diff_threshold,
                "blur_score": blur,
                "selector": self.actual_name,
                "mode_tag": self.mode_tag,
            }

        return {
            "keep": True,
            "reason": "first" if previous_image is None else "keep",
            "blur_score": blur,
            "diff_score": diff,
            "selector": self.actual_name,
            "mode_tag": self.mode_tag,
        }

    def should_keep(self, frame_or_processed_frame: Any, context: Dict[str, Any] | None = None) -> bool:
        return bool(self.decision(frame_or_processed_frame, context).get("keep"))

    def status(self) -> Dict[str, Any]:
        data = super().status()
        data.update({
            "min_interval_sec": self.min_interval_sec,
            "blur_threshold": self.blur_threshold,
            "diff_threshold": self.diff_threshold,
            "diff_resize_width": self.diff_resize_width,
        })
        return data
