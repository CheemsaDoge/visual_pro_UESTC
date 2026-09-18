#!/usr/bin/env python3
"""Stitch engine abstraction."""
from __future__ import annotations

from abc import ABC, abstractmethod
import copy
import time
from typing import List, Tuple


class StitchEngine(ABC):
    requested_name = "base"
    actual_name = "base"
    mode_tag = "stitch_base"

    def _begin_run_detail(self, image_paths: List[str], auto_crop: bool) -> dict:
        self.last_run_detail = {
            "engine": self.actual_name,
            "mode": self.mode_tag,
            "parameters": {"auto_crop": bool(auto_crop), "input_count": len(image_paths)},
            "stages": [],
            "fallback": {"used": False},
        }
        return self.last_run_detail

    def _record_stage(self, name: str, started: float, **detail) -> None:
        if not hasattr(self, "last_run_detail"):
            self.last_run_detail = {"stages": []}
        item = {"name": name, "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3)}
        item.update(detail)
        self.last_run_detail.setdefault("stages", []).append(item)

    def get_last_run_detail(self) -> dict:
        return copy.deepcopy(getattr(self, "last_run_detail", {}))

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
