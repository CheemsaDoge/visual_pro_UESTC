#!/usr/bin/env python3
"""Keyframe selector abstraction."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class KeyframeSelector(ABC):
    requested_name = "base"
    actual_name = "base"
    mode_tag = "selector_base"

    @abstractmethod
    def should_keep(self, frame_or_processed_frame: Any, context: Dict[str, Any] | None = None) -> bool:
        raise NotImplementedError

    def decision(self, frame_or_processed_frame: Any, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        keep = self.should_keep(frame_or_processed_frame, context)
        return {
            "keep": keep,
            "reason": "keep" if keep else "drop",
            "selector": self.actual_name,
            "mode_tag": self.mode_tag,
        }

    def status(self) -> Dict[str, Any]:
        return {
            "requested": self.requested_name,
            "actual": self.actual_name,
            "mode_tag": self.mode_tag,
            "available": True,
            "fallback": False,
            "reason": "",
        }
