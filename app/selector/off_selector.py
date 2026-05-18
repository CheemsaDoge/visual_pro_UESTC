#!/usr/bin/env python3
"""Selector disabled: keep every frame that reaches the auto-save cadence."""
from __future__ import annotations

from typing import Any, Dict

from app.selector.base import KeyframeSelector


class OffSelector(KeyframeSelector):
    requested_name = "off"
    actual_name = "off"
    mode_tag = "selector_off"

    def should_keep(self, frame_or_processed_frame: Any, context: Dict[str, Any] | None = None) -> bool:
        return True

    def decision(self, frame_or_processed_frame: Any, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return {
            "keep": True,
            "reason": "selector_off",
            "selector": self.actual_name,
            "mode_tag": self.mode_tag,
        }
