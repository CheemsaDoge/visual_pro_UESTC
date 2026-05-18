#!/usr/bin/env python3
"""Geometry acceleration abstraction."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple


class GeometryEngine(ABC):
    requested_name = "base"
    actual_name = "base"
    mode_tag = "base"

    @abstractmethod
    def warp_perspective(self, image: Any, matrix: Any, dsize: Tuple[int, int], **kwargs: Any) -> Any:
        raise NotImplementedError

    @abstractmethod
    def remap(self, image: Any, map1: Any, map2: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def status(self) -> Dict[str, Any]:
        return {
            "requested": self.requested_name,
            "actual": self.actual_name,
            "mode_tag": self.mode_tag,
            "available": True,
            "fallback": False,
            "reason": "",
        }
