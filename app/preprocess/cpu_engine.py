#!/usr/bin/env python3
"""CPU implementation for preview/save preprocessing."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from app import config
from app.preprocess.base import PreprocessEngine
from app.schemas import FramePacket, ProcessedFrame


class CpuPreprocessEngine(PreprocessEngine):
    requested_name = "cpu"
    actual_name = "cpu"
    mode_tag = "cpu_base"

    def __init__(
        self,
        rotation: str | None = None,
        preview_max_dim: int | None = None,
        preview_jpeg_quality: int | None = None,
        save_jpeg_quality: int | None = None,
    ) -> None:
        self.rotation = rotation if rotation is not None else config.CAMERA_ROTATION
        self.preview_max_dim = config.CAMERA_PREVIEW_MAX_DIM if preview_max_dim is None else int(preview_max_dim)
        self.preview_jpeg_quality = (
            config.CAMERA_PREVIEW_JPEG_QUALITY if preview_jpeg_quality is None else int(preview_jpeg_quality)
        )
        self.save_jpeg_quality = config.CAMERA_JPEG_QUALITY if save_jpeg_quality is None else int(save_jpeg_quality)

    def _to_bgr(self, frame_packet: FramePacket):
        import cv2
        import numpy as np

        data = frame_packet.data
        fmt = (frame_packet.pixel_format or "BGR").upper()
        if data is None:
            raise ValueError("frame data is empty")

        # OpenCV/GStreamer capture already yields BGR ndarray in the current path.
        if fmt in ("BGR", "BGR24"):
            return data
        if fmt == "RGB":
            return cv2.cvtColor(data, cv2.COLOR_RGB2BGR)
        if fmt in ("GRAY", "GREY", "Y8"):
            return cv2.cvtColor(data, cv2.COLOR_GRAY2BGR)
        if fmt in ("NV12", "NV21"):
            arr = self._nv12_tight_view(frame_packet)
            code = cv2.COLOR_YUV2BGR_NV21 if fmt == "NV21" else cv2.COLOR_YUV2BGR_NV12
            return cv2.cvtColor(arr, code)
        # Safe fallback: assume caller supplied an OpenCV-compatible BGR image.
        return data

    @staticmethod
    def _nv12_tight_view(frame_packet: FramePacket):
        import numpy as np

        width = int(frame_packet.width)
        height = int(frame_packet.height)
        stride_w = int(frame_packet.stride_w or width)
        stride_h = int(frame_packet.stride_h or height)
        expected = width * height * 3 // 2
        data = frame_packet.data
        if not isinstance(data, (bytes, bytearray, memoryview)):
            arr = np.asarray(data, dtype=np.uint8)
            if arr.size < expected:
                raise ValueError(f"short NV12 frame: {arr.size} < {expected}")
            if arr.ndim == 2 and arr.shape[1] == width and arr.shape[0] >= height * 3 // 2:
                return np.ascontiguousarray(arr[:height * 3 // 2, :width])
            return np.ascontiguousarray(arr.reshape(-1)[:expected].reshape((height * 3 // 2, width)))
        raw = np.frombuffer(data, dtype=np.uint8)
        if stride_w == width and stride_h == height:
            if raw.size < expected:
                raise ValueError(f"short NV12 frame: {raw.size} < {expected}")
            return np.ascontiguousarray(raw[:expected].reshape((height * 3 // 2, width)))
        uv_offset = int(frame_packet.meta.get("uv_offset") or (stride_w * stride_h))
        needed = uv_offset + stride_w * (height // 2)
        if raw.size < needed:
            raise ValueError(f"short strided NV12 frame: {raw.size} < {needed}")
        y = raw[: stride_w * stride_h].reshape((stride_h, stride_w))[:height, :width]
        uv = raw[uv_offset: uv_offset + stride_w * (height // 2)].reshape((height // 2, stride_w))[:, :width]
        return np.ascontiguousarray(np.vstack((y, uv)))

    def _rotate(self, bgr_image):
        import cv2

        if bgr_image is None or self.rotation == "none":
            return bgr_image
        if self.rotation == "ccw90":
            return cv2.rotate(bgr_image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if self.rotation == "cw90":
            return cv2.rotate(bgr_image, cv2.ROTATE_90_CLOCKWISE)
        if self.rotation == "180":
            return cv2.rotate(bgr_image, cv2.ROTATE_180)
        return bgr_image

    def _resize_preview(self, bgr_image):
        import cv2

        if bgr_image is None or self.preview_max_dim <= 0:
            return bgr_image
        try:
            height, width = bgr_image.shape[:2]
        except Exception:
            return bgr_image
        longer = max(width, height)
        if longer <= self.preview_max_dim:
            return bgr_image
        scale = self.preview_max_dim / float(longer)
        target_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        return cv2.resize(bgr_image, target_size, interpolation=cv2.INTER_AREA)

    @staticmethod
    def _dimensions(image) -> Tuple[int, int]:
        try:
            height, width = image.shape[:2]
            return int(width), int(height)
        except Exception:
            return 0, 0

    def _processed(self, frame_packet: FramePacket, bgr_image, preview_jpeg: bytes, purpose: str) -> ProcessedFrame:
        width, height = self._dimensions(bgr_image)
        return ProcessedFrame(
            seq=frame_packet.seq,
            timestamp=frame_packet.timestamp,
            width=width,
            height=height,
            bgr_image=bgr_image,
            preview_jpeg=preview_jpeg,
            meta={
                "engine": self.actual_name,
                "requested_engine": self.requested_name,
                "mode_tag": self.mode_tag,
                "purpose": purpose,
                "rotation": self.rotation,
                "source_pixel_format": frame_packet.pixel_format,
            },
        )

    def process_for_preview(self, frame_packet: FramePacket) -> ProcessedFrame:
        import cv2

        bgr = self._rotate(self._to_bgr(frame_packet))
        preview = self._resize_preview(bgr)
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(self.preview_jpeg_quality)]
        ok, encoded = cv2.imencode(".jpg", preview, encode_params)
        preview_jpeg = encoded.tobytes() if ok else b""
        return self._processed(frame_packet, bgr, preview_jpeg, "preview")

    def process_for_save(self, frame_packet: FramePacket) -> ProcessedFrame:
        bgr = self._rotate(self._to_bgr(frame_packet))
        return self._processed(frame_packet, bgr, b"", "save")

    def status(self) -> Dict[str, Any]:
        data = super().status()
        data.update({
            "rotation": self.rotation,
            "preview_max_dim": self.preview_max_dim,
            "preview_jpeg_quality": self.preview_jpeg_quality,
            "save_jpeg_quality": self.save_jpeg_quality,
        })
        return data
