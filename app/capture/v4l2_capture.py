#!/usr/bin/env python3
"""v4l2-ctl based NV12 single-frame capture fallback."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time

from app.capture.base import CaptureDevice
from app.schemas import FramePacket


class V4L2CtlNv12Capture(CaptureDevice):
    def __init__(
        self,
        cv2_module,
        device: str,
        width: int,
        height: int,
        fps: int,
        pixel_format: str,
        buffer_count: int,
        timeout_sec: float = 5.0,
        raw_packet: bool = False,
    ):
        self.cv2 = cv2_module
        self.device = device
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.pixel_format = (str(pixel_format or "NV12").upper())
        self.buffer_count = int(buffer_count or 4)
        self.timeout_sec = float(timeout_sec)
        self.raw_packet = bool(raw_packet)
        self.last_error = ""
        self._tmp_path = os.path.join("/tmp", f"myui_camera_{os.getpid()}_{threading.get_ident()}.nv12")
        self._opened = bool(self.device and os.path.exists(self.device) and shutil.which("v4l2-ctl"))
        if not self._opened:
            if not self.device or not os.path.exists(self.device):
                self.last_error = f"device not found: {self.device}"
            elif not shutil.which("v4l2-ctl"):
                self.last_error = "v4l2-ctl not found"

    def isOpened(self) -> bool:
        return bool(self._opened)

    def set(self, *_args, **_kwargs) -> bool:
        return False

    def release(self) -> None:
        try:
            if self._tmp_path and os.path.exists(self._tmp_path):
                os.unlink(self._tmp_path)
        except Exception:
            pass
        self._opened = False

    def _decode_nv12(self, raw: bytes):
        import numpy as np

        expected = self.width * self.height * 3 // 2
        if len(raw) < expected:
            raise ValueError(f"short NV12 frame: {len(raw)} < {expected}")
        yuv = np.frombuffer(raw[:expected], dtype=np.uint8).reshape((self.height * 3 // 2, self.width))
        code = self.cv2.COLOR_YUV2BGR_NV21 if self.pixel_format == "NV21" else self.cv2.COLOR_YUV2BGR_NV12
        return self.cv2.cvtColor(yuv, code)

    def _infer_stride(self, raw_size: int) -> tuple[int, int, bool, str]:
        tight = self.width * self.height * 3 // 2
        if raw_size == tight:
            return self.width, self.height, False, "tight-buffer-size"
        for alignment in (16, 32, 64, 128, 256):
            stride_w = ((self.width + alignment - 1) // alignment) * alignment
            denominator = 3 * stride_w
            numerator = raw_size * 2
            if denominator > 0 and numerator % denominator == 0:
                stride_h = numerator // denominator
                if stride_h >= self.height:
                    return int(stride_w), int(stride_h), True, f"inferred-align{alignment}"
        denominator = 3 * self.width
        numerator = raw_size * 2
        stride_h = self.height
        if denominator > 0 and numerator % denominator == 0:
            stride_h = max(self.height, numerator // denominator)
        return self.width, int(stride_h), True, "inferred-width"

    def _packet_from_raw(self, raw: bytes) -> FramePacket:
        expected = self.width * self.height * 3 // 2
        if len(raw) < expected:
            raise ValueError(f"short NV12 frame: {len(raw)} < {expected}")
        stride_w, stride_h, stride_inferred, stride_source = self._infer_stride(len(raw))
        timestamp = time.time()
        return FramePacket(
            seq=0,
            timestamp=timestamp,
            width=self.width,
            height=self.height,
            pixel_format=self.pixel_format,
            source=f"v4l2-ctl:{self.device}",
            data=raw,
            meta={
                "capture_backend": "v4l2ctl_nv12_raw",
                "stride_source": stride_source,
                "uv_offset": stride_w * stride_h,
            },
            stride_w=stride_w,
            stride_h=stride_h,
            timestamp_ns=int(timestamp * 1000000000),
            buffer_size=len(raw),
            stride_inferred=stride_inferred,
        )

    def read(self):
        if not self.isOpened():
            return False, None
        tmp_path = self._tmp_path
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass
        cmd = [
            "v4l2-ctl",
            "-d", self.device,
            f"--set-fmt-video=width={self.width},height={self.height},pixelformat={self.pixel_format}",
            f"--stream-mmap={self.buffer_count}",
            "--stream-count=1",
            f"--stream-to={tmp_path}",
        ]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.timeout_sec)
        except Exception as exc:
            self.last_error = f"v4l2-ctl exception: {exc}"
            return False, None
        if proc.returncode != 0:
            stderr = (proc.stderr or b"").decode("utf-8", "replace").strip()
            stdout = (proc.stdout or b"").decode("utf-8", "replace").strip()
            detail = stderr or stdout or f"exit={proc.returncode}"
            self.last_error = f"v4l2-ctl failed: {detail}"
            return False, None
        try:
            with open(tmp_path, "rb") as f:
                raw = f.read()
            frame = self._packet_from_raw(raw) if self.raw_packet else self._decode_nv12(raw)
        except Exception as exc:
            self.last_error = f"NV12 decode failed: {exc}"
            return False, None
        self.last_error = ""
        return True, frame
