#!/usr/bin/env python3
"""Shared data objects moving frames through capture/preprocess/select/stitch."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class FramePacket:
    seq: int
    timestamp: float
    width: int
    height: int
    pixel_format: str
    source: str
    data: Any
    meta: Dict[str, Any] = field(default_factory=dict)
    stride_w: int = 0
    stride_h: int = 0
    timestamp_ns: int = 0
    buffer_size: int = 0
    stride_inferred: bool = False

    def __post_init__(self) -> None:
        self.width = int(self.width or 0)
        self.height = int(self.height or 0)
        self.pixel_format = (self.pixel_format or "").upper()
        if not self.stride_w:
            self.stride_w = self.width
        if not self.stride_h:
            self.stride_h = self.height
        self.stride_w = int(self.stride_w or 0)
        self.stride_h = int(self.stride_h or 0)
        if not self.timestamp_ns and self.timestamp:
            self.timestamp_ns = int(float(self.timestamp) * 1000000000)
        self.timestamp_ns = int(self.timestamp_ns or 0)
        if not self.buffer_size:
            self.buffer_size = self._data_nbytes(self.data)
        self.buffer_size = int(self.buffer_size or 0)
        self.stride_inferred = bool(self.stride_inferred)

    @staticmethod
    def _data_nbytes(data: Any) -> int:
        if data is None:
            return 0
        if isinstance(data, (bytes, bytearray, memoryview)):
            return len(data)
        nbytes = getattr(data, "nbytes", None)
        if nbytes is not None:
            try:
                return int(nbytes)
            except Exception:
                return 0
        size = getattr(data, "size", None)
        itemsize = getattr(data, "itemsize", 1)
        if size is not None:
            try:
                return int(size) * int(itemsize or 1)
            except Exception:
                return 0
        return 0


@dataclass
class ProcessedFrame:
    seq: int
    timestamp: float
    width: int
    height: int
    bgr_image: Any
    preview_jpeg: bytes = b""
    meta: Dict[str, Any] = field(default_factory=dict)
