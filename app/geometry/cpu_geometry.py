#!/usr/bin/env python3
"""CPU/OpenCV geometry operations."""
from __future__ import annotations

from typing import Any, Tuple

from app.geometry.base import GeometryEngine


class CpuGeometryEngine(GeometryEngine):
    requested_name = "cpu"
    actual_name = "cpu"
    mode_tag = "geometry_cpu"

    def warp_perspective(self, image: Any, matrix: Any, dsize: Tuple[int, int], **kwargs: Any) -> Any:
        import cv2

        return cv2.warpPerspective(image, matrix, dsize, **kwargs)

    def remap(self, image: Any, map1: Any, map2: Any, **kwargs: Any) -> Any:
        import cv2

        return cv2.remap(image, map1, map2, **kwargs)
