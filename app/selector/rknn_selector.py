#!/usr/bin/env python3
"""RKNN selector placeholder.

NPU/RKNN is planned after RGA and OpenCL stages.  Until a model/runtime is
configured, this selector falls back to a CPU basic selector.
"""
from __future__ import annotations

from typing import Any, Dict

from app.selector.base import KeyframeSelector
from app.selector.cpu_selector import CpuSelector
from app.utils.log import log_event


class RknnSelector(KeyframeSelector):
    requested_name = "rknn"

    def __init__(self, fallback: CpuSelector | None = None) -> None:
        self.fallback = fallback or CpuSelector()
        self.actual_name = self.fallback.actual_name
        self.mode_tag = "rknn_fallback_cpu_basic"
        self.reason = "RKNN model/runtime not configured in current stage"
        log_event("selector", f"requested=rknn actual={self.actual_name} fallback=true reason={self.reason}")

    def should_keep(self, frame_or_processed_frame: Any, context: Dict[str, Any] | None = None) -> bool:
        return self.fallback.should_keep(frame_or_processed_frame, context)

    def decision(self, frame_or_processed_frame: Any, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        data = self.fallback.decision(frame_or_processed_frame, context)
        data.update({
            "requested_selector": self.requested_name,
            "selector": self.actual_name,
            "mode_tag": self.mode_tag,
            "fallback_reason": self.reason,
        })
        return data

    def status(self) -> Dict[str, Any]:
        return {
            "requested": self.requested_name,
            "actual": self.actual_name,
            "mode_tag": self.mode_tag,
            "available": False,
            "fallback": True,
            "reason": self.reason,
            "fallback_selector": self.fallback.status(),
        }
