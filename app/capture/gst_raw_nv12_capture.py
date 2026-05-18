#!/usr/bin/env python3
"""Raw NV12 GStreamer appsink capture for RK3588 camera smoke tests."""
from __future__ import annotations

import time
from typing import Any

from app.capture.base import CaptureDevice
from app.capture.gst_capture import build_raw_nv12_pipeline
from app.schemas import FramePacket


class OpenCvGstRawNv12Capture(CaptureDevice):
    """Raw NV12 capture through OpenCV's GStreamer backend.

    This avoids the board-side Python GI dependency while preserving the same
    appsink NV12 boundary used by the GI implementation below.
    """

    def __init__(
        self,
        cv2,
        device: str,
        width: int,
        height: int,
        fps: int,
        pixel_format: str = "NV12",
        timeout_sec: float = 5.0,
    ) -> None:
        self.cv2 = cv2
        self.device = device
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.pixel_format = (pixel_format or "NV12").upper()
        self.timeout_sec = float(timeout_sec)
        self.pipeline_text = build_raw_nv12_pipeline(device, width, height, fps, self.pixel_format).replace(
            "appsink name=sink ",
            "appsink ",
        )
        self.last_error = ""
        self.cap = None
        self._open()

    def _open(self) -> None:
        try:
            api = getattr(self.cv2, "CAP_GSTREAMER", None)
            self.cap = self.cv2.VideoCapture(self.pipeline_text, api) if api is not None else self.cv2.VideoCapture(self.pipeline_text)
            if not self.cap or not self.cap.isOpened():
                self.last_error = "OpenCV GStreamer raw NV12 pipeline did not open"
                self.release()
                return
            try:
                self.cap.set(self.cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
        except Exception as exc:
            self.last_error = f"OpenCV GStreamer raw NV12 open failed: {exc}"
            self.release()

    def isOpened(self) -> bool:
        try:
            return bool(self.cap is not None and self.cap.isOpened())
        except Exception:
            return False

    def release(self) -> None:
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass
        self.cap = None

    def set(self, *args, **kwargs) -> bool:
        try:
            return bool(self.cap is not None and self.cap.set(*args, **kwargs))
        except Exception:
            return False

    def read(self):
        try:
            packet = self.read_packet()
            return True, packet
        except Exception as exc:
            self.last_error = str(exc)
            return False, None

    def read_packet(self, seq: int = 0, timestamp: float | None = None) -> FramePacket:
        if not self.isOpened():
            raise RuntimeError(self.last_error or "OpenCV raw NV12 capture is not open")
        ok, frame = self.cap.read()
        if not ok or frame is None:
            raise RuntimeError("OpenCV GStreamer appsink returned no NV12 frame")
        if timestamp is None:
            timestamp = time.time()
        return self._frame_to_packet(frame, seq=seq, timestamp=timestamp)

    def _frame_to_packet(self, frame, seq: int, timestamp: float) -> FramePacket:
        expected = self.width * self.height * 3 // 2
        buffer_size = int(getattr(frame, "nbytes", 0) or 0)
        if buffer_size < expected:
            raise RuntimeError(f"short OpenCV NV12 frame: {buffer_size} < {expected}")

        shape = tuple(getattr(frame, "shape", ()) or ())
        strides = tuple(getattr(frame, "strides", ()) or ())
        stride_w = self.width
        stride_h = self.height
        stride_inferred = False
        stride_source = "opencv-gstreamer-tight"

        if len(shape) >= 2 and len(strides) >= 1 and int(strides[0] or 0) >= self.width:
            stride_w = int(strides[0])
            stride_source = "opencv-gstreamer-row-stride"
        if buffer_size == expected:
            stride_w = self.width
            stride_h = self.height
            stride_source = "opencv-gstreamer-tight"
        elif stride_w > 0:
            inferred_h = (buffer_size * 2) // (3 * stride_w)
            if inferred_h >= self.height and inferred_h * stride_w * 3 // 2 == buffer_size:
                stride_h = int(inferred_h)
                stride_inferred = True
                stride_source = "opencv-gstreamer-buffer-size"
            else:
                stride_inferred = True

        meta = {
            "gst_pipeline": self.pipeline_text,
            "capture_backend": "gst_nv12_raw",
            "stride_source": stride_source,
            "uv_offset": int(stride_w * stride_h),
            "opencv_shape": shape,
            "opencv_strides": strides,
        }
        return FramePacket(
            seq=int(seq),
            timestamp=float(timestamp),
            width=self.width,
            height=self.height,
            pixel_format=self.pixel_format,
            source=f"gst-opencv-nv12:{self.device}",
            data=frame,
            meta=meta,
            stride_w=int(stride_w),
            stride_h=int(stride_h),
            timestamp_ns=int(timestamp * 1000000000),
            buffer_size=buffer_size,
            stride_inferred=bool(stride_inferred),
        )


class GstRawNv12Capture(CaptureDevice):
    def __init__(
        self,
        device: str,
        width: int,
        height: int,
        fps: int,
        pixel_format: str = "NV12",
        timeout_sec: float = 5.0,
    ) -> None:
        self.device = device
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.pixel_format = (pixel_format or "NV12").upper()
        self.timeout_sec = float(timeout_sec)
        self.pipeline_text = build_raw_nv12_pipeline(device, width, height, fps, self.pixel_format)
        self.last_error = ""
        self._opened = False
        self.Gst = None
        self.GstVideo = None
        self.pipeline = None
        self.sink = None
        self._open()

    def _open(self) -> None:
        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst

            try:
                gi.require_version("GstVideo", "1.0")
                from gi.repository import GstVideo
            except Exception:
                GstVideo = None
            Gst.init(None)
            self.Gst = Gst
            self.GstVideo = GstVideo
            self.pipeline = Gst.parse_launch(self.pipeline_text)
            self.sink = self.pipeline.get_by_name("sink")
            if self.sink is None:
                self.last_error = "appsink named sink not found"
                return
            self.pipeline.set_state(Gst.State.PLAYING)
            ret, _state, _pending = self.pipeline.get_state(int(self.timeout_sec * Gst.SECOND))
            if ret == Gst.StateChangeReturn.FAILURE:
                self.last_error = "GStreamer pipeline failed to enter PLAYING"
                self.release()
                return
            self._opened = True
        except Exception as exc:
            self.last_error = f"GStreamer raw NV12 open failed: {exc}"
            self.release()

    def isOpened(self) -> bool:
        return bool(self._opened and self.pipeline is not None and self.sink is not None)

    def release(self) -> None:
        try:
            if self.pipeline is not None and self.Gst is not None:
                self.pipeline.set_state(self.Gst.State.NULL)
        except Exception:
            pass
        self._opened = False

    def set(self, *_args, **_kwargs) -> bool:
        return False

    def read(self):
        try:
            return True, self.read_packet()
        except Exception as exc:
            self.last_error = str(exc)
            return False, None

    def read_packet(self, seq: int = 0, timestamp: float | None = None) -> FramePacket:
        if not self.isOpened():
            raise RuntimeError(self.last_error or "raw NV12 capture is not open")
        sample = self._pull_sample()
        packet = self._sample_to_packet(sample, seq=seq, timestamp=timestamp)
        if packet.pixel_format != "NV12":
            raise RuntimeError(f"appsink format is {packet.pixel_format}, expected NV12")
        return packet

    def _pull_sample(self):
        timeout_ns = int(max(0.1, self.timeout_sec) * 1000000000)
        try:
            sample = self.sink.emit("try-pull-sample", timeout_ns)
        except TypeError:
            sample = self.sink.emit("pull-sample")
        if sample is None:
            raise RuntimeError(f"appsink returned no sample within {self.timeout_sec:.1f}s")
        return sample

    def _sample_to_packet(self, sample, seq: int, timestamp: float | None) -> FramePacket:
        buffer = sample.get_buffer()
        caps = sample.get_caps()
        if buffer is None:
            raise RuntimeError("GstSample has no buffer")
        if caps is None or caps.get_size() < 1:
            raise RuntimeError("GstSample has no caps")
        fmt, width, height = self._caps_format_size(caps)
        ok, map_info = buffer.map(self.Gst.MapFlags.READ)
        if not ok:
            raise RuntimeError("failed to map GstBuffer for read")
        try:
            raw = bytes(map_info.data)
        finally:
            buffer.unmap(map_info)
        timestamp_ns = self._buffer_timestamp_ns(buffer)
        if timestamp is None:
            timestamp = timestamp_ns / 1000000000.0 if timestamp_ns > 0 else time.time()
        stride = self._extract_stride(buffer, caps, width, height, len(raw))
        meta = {
            "gst_caps": caps.to_string(),
            "gst_pipeline": self.pipeline_text,
            "stride_source": stride.get("source", ""),
            "uv_offset": stride.get("uv_offset", 0),
        }
        return FramePacket(
            seq=int(seq),
            timestamp=float(timestamp),
            width=width,
            height=height,
            pixel_format=fmt,
            source="camera",
            data=raw,
            meta=meta,
            stride_w=int(stride["stride_w"]),
            stride_h=int(stride["stride_h"]),
            timestamp_ns=int(timestamp_ns),
            buffer_size=len(raw),
            stride_inferred=bool(stride["stride_inferred"]),
        )

    @staticmethod
    def _caps_format_size(caps) -> tuple[str, int, int]:
        structure = caps.get_structure(0)
        fmt = (structure.get_string("format") or "").upper()
        ok_w, width = structure.get_int("width")
        ok_h, height = structure.get_int("height")
        if not fmt:
            raise RuntimeError(f"caps do not include format: {caps.to_string()}")
        if not ok_w or not ok_h:
            raise RuntimeError(f"caps do not include width/height: {caps.to_string()}")
        return fmt, int(width), int(height)

    def _buffer_timestamp_ns(self, buffer) -> int:
        clock_none = getattr(self.Gst, "CLOCK_TIME_NONE", None)
        for value in (getattr(buffer, "pts", None), getattr(buffer, "dts", None)):
            if value is None:
                continue
            try:
                ivalue = int(value)
            except Exception:
                continue
            if clock_none is not None and ivalue == int(clock_none):
                continue
            if ivalue >= 0:
                return ivalue
        return int(time.time_ns())

    def _extract_stride(self, buffer, caps, width: int, height: int, buffer_size: int) -> dict[str, Any]:
        meta_stride = self._stride_from_video_meta(buffer)
        if meta_stride:
            return self._complete_stride(meta_stride, width, height, buffer_size, source="GstVideoMeta")
        info_stride = self._stride_from_video_info(caps)
        if info_stride:
            return self._complete_stride(info_stride, width, height, buffer_size, source="GstVideoInfo")
        return self._infer_stride(width, height, buffer_size)

    def _stride_from_video_meta(self, buffer) -> dict[str, Any] | None:
        if self.GstVideo is None or not hasattr(self.GstVideo, "buffer_get_video_meta"):
            return None
        try:
            meta = self.GstVideo.buffer_get_video_meta(buffer)
        except Exception:
            return None
        if meta is None:
            return None
        return {
            "stride_w": self._list_int(getattr(meta, "stride", None), 0),
            "uv_offset": self._list_int(getattr(meta, "offset", None), 1),
        }

    def _stride_from_video_info(self, caps) -> dict[str, Any] | None:
        if self.GstVideo is None or not hasattr(self.GstVideo, "VideoInfo"):
            return None
        try:
            info = self.GstVideo.VideoInfo()
            ok = info.from_caps(caps)
            if not ok:
                return None
            return {
                "stride_w": self._list_int(getattr(info, "stride", None), 0),
                "uv_offset": self._list_int(getattr(info, "offset", None), 1),
            }
        except Exception:
            try:
                info = self.GstVideo.VideoInfo.new_from_caps(caps)
                return {
                    "stride_w": self._list_int(getattr(info, "stride", None), 0),
                    "uv_offset": self._list_int(getattr(info, "offset", None), 1),
                }
            except Exception:
                return None

    @staticmethod
    def _list_int(values, index: int) -> int:
        try:
            value = values[index]
            return int(value or 0)
        except Exception:
            return 0

    def _complete_stride(self, stride: dict[str, Any], width: int, height: int, buffer_size: int, source: str) -> dict[str, Any]:
        stride_w = int(stride.get("stride_w") or width)
        uv_offset = int(stride.get("uv_offset") or 0)
        stride_h = height
        if stride_w > 0 and uv_offset > 0:
            stride_h = max(height, int(uv_offset // stride_w))
        elif stride_w > 0:
            inferred = self._infer_stride_h(stride_w, height, buffer_size)
            stride_h = inferred or height
        return {
            "stride_w": stride_w,
            "stride_h": stride_h,
            "uv_offset": uv_offset or stride_w * stride_h,
            "stride_inferred": False,
            "source": source,
        }

    @staticmethod
    def _infer_stride_h(stride_w: int, height: int, buffer_size: int) -> int:
        if stride_w <= 0:
            return 0
        numerator = int(buffer_size) * 2
        denominator = 3 * int(stride_w)
        if denominator > 0 and numerator % denominator == 0:
            value = numerator // denominator
            if value >= height:
                return int(value)
        return 0

    def _infer_stride(self, width: int, height: int, buffer_size: int) -> dict[str, Any]:
        tight = width * height * 3 // 2
        if buffer_size == tight:
            return {
                "stride_w": width,
                "stride_h": height,
                "uv_offset": width * height,
                "stride_inferred": True,
                "source": "tight-buffer-size",
            }
        for alignment in (16, 32, 64, 128, 256):
            stride_w = ((width + alignment - 1) // alignment) * alignment
            stride_h = self._infer_stride_h(stride_w, height, buffer_size)
            if stride_h:
                return {
                    "stride_w": stride_w,
                    "stride_h": stride_h,
                    "uv_offset": stride_w * stride_h,
                    "stride_inferred": True,
                    "source": f"inferred-align{alignment}",
                }
        stride_h = self._infer_stride_h(width, height, buffer_size) or height
        return {
            "stride_w": width,
            "stride_h": stride_h,
            "uv_offset": width * stride_h,
            "stride_inferred": True,
            "source": "inferred-width",
        }
