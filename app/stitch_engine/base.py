#!/usr/bin/env python3
"""Stitch engine abstraction."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Tuple


class StitchEngine(ABC):
    requested_name = "base"
    actual_name = "base"
    mode_tag = "stitch_base"

    @abstractmethod
    def stitch(self, image_paths: List[str], output_path: str, auto_crop: bool = False) -> Tuple[bool, str]:
        raise NotImplementedError

    def status(self) -> dict:
        return {
            "requested": self.requested_name,
            "actual": self.actual_name,
            "mode_tag": self.mode_tag,
            "available": True,
            "fallback": False,
            "reason": "",
        }
