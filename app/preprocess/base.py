#!/usr/bin/env python3
"""Preprocess engine abstraction.

This is the first accelerator boundary in the project.  Camera code should pass
captured FramePacket objects through this interface instead of directly calling
OpenCV resize/rotate/color conversion helpers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any

from app.schemas import FramePacket, ProcessedFrame


class PreprocessEngine(ABC):
    requested_name = "base"
    actual_name = "base"
    mode_tag = "base"

    @abstractmethod
    def process_for_preview(self, frame_packet: FramePacket) -> ProcessedFrame:
        raise NotImplementedError

    @abstractmethod
    def process_for_save(self, frame_packet: FramePacket) -> ProcessedFrame:
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
