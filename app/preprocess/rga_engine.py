#!/usr/bin/env python3
"""RGA preprocess engine using a tiny ctypes wrapper plus CPU fallback.

The real accelerator boundary is intentionally narrow: Python only loads
``native/rga/libmyui_rga.so`` and passes contiguous NV12 bytes plus output BGR
buffer pointers.  All Rockchip im2d/RGA details stay inside the native wrapper.
"""
from __future__ import annotations

import ctypes
import glob
import os
import time
from typing import Any, Dict, Iterable, Tuple

from app import config
from app.preprocess.base import PreprocessEngine
from app.preprocess.cpu_engine import CpuPreprocessEngine
from app.schemas import FramePacket, ProcessedFrame
from app.utils.log import log_event


class RgaPreprocessEngine(PreprocessEngine):
    requested_name = "rga"

    def __init__(
        self,
        fallback: CpuPreprocessEngine | None = None,
        lib_path: str | None = None,
        require_rga: bool = False,
    ) -> None:
        self.fallback = fallback or CpuPreprocessEngine()
        self.require_rga = bool(require_rga)
        self.rotation = self.fallback.rotation
        self.preview_max_dim = self.fallback.preview_max_dim
        self.preview_jpeg_quality = self.fallback.preview_jpeg_quality
        self.lib_path_requested = lib_path or os.environ.get("MYUI_RGA_LIB", "")
        self.lib = None
        self.rga_runtime_lib = None
        self.lib_path = ""
        self.lib_version = ""
        self.candidate_paths = list(self._candidate_lib_paths())
        self.load_error = ""
        self.wrapper_available = False
        self.active_calls = 0
        self.fallback_calls = 0
        self.last_reason = "not initialized"
        self.last_error = "not initialized"
        self.last_native_message = ""
        self.available, self.reason, self.probe = self._probe_rga()
        self._load_wrapper()
        if self.wrapper_available:
            self.actual_name = "rga"
            self.mode_tag = "rga_ready"
            self.last_reason = "wrapper loaded; waiting for NV12 frame"
            self.last_error = "ok"
            log_event(
                "preprocess",
                f"requested=rga actual=rga_ready fallback=false lib={self.lib_path} version={self.lib_version}",
            )
        else:
            self.actual_name = "cpu"
            self.mode_tag = "rga_fallback_cpu"
            self.last_reason = self.load_error or self.reason
            self.last_error = self.last_reason
            log_event(
                "preprocess",
                "requested=rga actual=rga_fallback_cpu fallback=true reason=" + self.last_reason,
            )

    @staticmethod
    def _probe_rga() -> tuple[bool, str, Dict[str, Any]]:
        device_candidates = sorted(glob.glob("/dev/rga*"))
        lib_candidates = []
        for pattern in (
            "/usr/lib*/librga.so*",
            "/usr/local/lib*/librga.so*",
            "/lib*/librga.so*",
            "/userdata/**/*.so",
        ):
            lib_candidates.extend(glob.glob(pattern, recursive=True))
        header_candidates = []
        for pattern in (
            "/usr/include/**/*rga*",
            "/usr/include/**/im2d.h",
            "/usr/include/**/RgaApi.h",
            "/usr/local/include/**/*rga*",
            "/usr/local/include/**/im2d.h",
            "/usr/local/include/**/RgaApi.h",
        ):
            header_candidates.extend(glob.glob(pattern, recursive=True))
        probe = {
            "devices": device_candidates,
            "libraries": sorted(set(lib_candidates))[:32],
            "headers": sorted(set(header_candidates))[:32],
            "wrapper_candidates": list(RgaPreprocessEngine._candidate_lib_paths_static("")),
        }
        if not device_candidates:
            return False, "no /dev/rga* device found", probe
        if not lib_candidates:
            return False, "RGA device exists but librga.so not found", probe
        return True, "RGA device and librga detected", probe

    @staticmethod
    def _candidate_lib_paths_static(explicit: str) -> Iterable[str]:
        base_dir = getattr(config, "BASE_DIR", os.getcwd())
        candidates = []
        if explicit:
            candidates.append(explicit)
        candidates.extend([
            os.path.join(base_dir, "native", "rga", "libmyui_rga.so"),
            os.path.join(os.getcwd(), "native", "rga", "libmyui_rga.so"),
            "/userdata/myui/native/rga/libmyui_rga.so",
            "/usr/local/lib/libmyui_rga.so",
            "/usr/lib/libmyui_rga.so",
            "/lib/libmyui_rga.so",
        ])
        seen = set()
        for path in candidates:
            if not path or path in seen:
                continue
            seen.add(path)
            yield path

    def _candidate_lib_paths(self) -> Iterable[str]:
        return self._candidate_lib_paths_static(self.lib_path_requested)

    def _load_wrapper(self) -> None:
        errors = []
        self._load_rga_runtime(errors)
        for path in self.candidate_paths:
            if not os.path.exists(path):
                continue
            try:
                lib = ctypes.CDLL(path)
                lib.myui_rga_available.argtypes = []
                lib.myui_rga_available.restype = ctypes.c_int
                lib.myui_rga_nv12_to_bgr.argtypes = [
                    ctypes.POINTER(ctypes.c_ubyte),
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.POINTER(ctypes.c_ubyte),
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                ]
                lib.myui_rga_nv12_to_bgr.restype = ctypes.c_int
                if hasattr(lib, "myui_rga_bgr_rotate"):
                    lib.myui_rga_bgr_rotate.argtypes = [
                        ctypes.POINTER(ctypes.c_ubyte),
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.POINTER(ctypes.c_ubyte),
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_int,
                    ]
                    lib.myui_rga_bgr_rotate.restype = ctypes.c_int
                if hasattr(lib, "myui_rga_bgrx_rotate_to_bgr"):
                    lib.myui_rga_bgrx_rotate_to_bgr.argtypes = [
                        ctypes.POINTER(ctypes.c_ubyte),
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.POINTER(ctypes.c_ubyte),
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_int,
                    ]
                    lib.myui_rga_bgrx_rotate_to_bgr.restype = ctypes.c_int
                if hasattr(lib, "myui_rga_last_error"):
                    lib.myui_rga_last_error.argtypes = []
                    lib.myui_rga_last_error.restype = ctypes.c_char_p
                if hasattr(lib, "myui_rga_version"):
                    lib.myui_rga_version.argtypes = []
                    lib.myui_rga_version.restype = ctypes.c_char_p
                available = bool(lib.myui_rga_available())
                if not available:
                    err = self._native_last_error(lib)
                    errors.append(f"{path}: myui_rga_available returned 0 ({err})")
                    continue
                self.lib = lib
                self.lib_path = path
                self.lib_version = self._native_version(lib)
                self.wrapper_available = True
                self.load_error = ""
                return
            except Exception as exc:
                errors.append(f"{path}: {exc}")
        self.load_error = "; ".join(errors) if errors else "libmyui_rga.so not found; run make in native/rga on target"

    def _load_rga_runtime(self, errors: list[str]) -> None:
        mode = getattr(ctypes, "RTLD_GLOBAL", 0)
        runtime_candidates = ["librga.so"]
        runtime_candidates.extend(self.probe.get("libraries", []))
        seen = set()
        for path in runtime_candidates:
            if not path or path in seen:
                continue
            seen.add(path)
            try:
                self.rga_runtime_lib = ctypes.CDLL(path, mode=mode)
                return
            except Exception as exc:
                errors.append(f"{path}: failed to load RGA runtime globally: {exc}")

    @staticmethod
    def _native_last_error(lib) -> str:
        try:
            if lib is not None and hasattr(lib, "myui_rga_last_error"):
                raw = lib.myui_rga_last_error()
                if raw:
                    return raw.decode("utf-8", "replace")
        except Exception:
            pass
        return ""

    @staticmethod
    def _native_version(lib) -> str:
        try:
            if lib is not None and hasattr(lib, "myui_rga_version"):
                raw = lib.myui_rga_version()
                if raw:
                    return raw.decode("utf-8", "replace")
        except Exception:
            pass
        return ""

    @staticmethod
    def _rotation_code(rotation: str | None) -> int:
        value = (rotation or "none").lower()
        if value == "ccw90":
            return 1
        if value == "cw90":
            return 2
        if value == "180":
            return 3
        return 0

    @staticmethod
    def _rotated_dimensions(width: int, height: int, rotate_code: int) -> Tuple[int, int]:
        if rotate_code in (1, 2):
            return int(height), int(width)
        return int(width), int(height)

    def _preview_dimensions(self, width: int, height: int) -> Tuple[int, int]:
        if self.preview_max_dim <= 0:
            return int(width), int(height)
        longer = max(int(width), int(height))
        if longer <= self.preview_max_dim:
            return int(width), int(height)
        scale = self.preview_max_dim / float(longer)
        return max(1, int(width * scale)), max(1, int(height * scale))

    @staticmethod
    def _nv12_view(frame_packet: FramePacket):
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

    @staticmethod
    def _data_size(data) -> int | None:
        if isinstance(data, (bytes, bytearray, memoryview)):
            return len(data)
        try:
            return int(getattr(data, "size"))
        except Exception:
            return None

    def _validate_native_call(self, frame_packet: FramePacket, dst_w: int, dst_h: int) -> Tuple[bool, str]:
        width = int(frame_packet.width)
        height = int(frame_packet.height)
        if width <= 0 or height <= 0 or dst_w <= 0 or dst_h <= 0:
            return False, f"invalid RGA dimensions src={width}x{height} dst={dst_w}x{dst_h}"
        if (width & 1) or (height & 1):
            return False, f"NV12 requires even width/height, got {width}x{height}"
        expected = width * height * 3 // 2
        actual = self._data_size(frame_packet.data)
        if actual is not None and actual < expected:
            return False, f"short NV12 frame: {actual} < {expected}"
        stride_w = int(frame_packet.stride_w or width)
        stride_h = int(frame_packet.stride_h or height)
        if stride_w < width or stride_h < height:
            return False, f"invalid NV12 stride {stride_w}x{stride_h} for frame {width}x{height}"
        return True, ""

    def _mark_fallback(self, reason: str) -> None:
        self.fallback_calls += 1
        self.actual_name = "cpu"
        self.mode_tag = "rga_fallback_cpu"
        self.last_reason = reason
        self.last_error = reason

    def _mark_active(self, reason: str = "ok") -> None:
        self.active_calls += 1
        self.actual_name = "rga"
        self.mode_tag = "rga_active"
        self.last_reason = reason
        self.last_error = "ok"

    def _fallback_processed(self, frame_packet: FramePacket, purpose: str, reason: str) -> ProcessedFrame:
        self._mark_fallback(reason)
        if self.require_rga:
            raise RuntimeError(f"RGA required but fallback would be used: {reason}")
        if purpose == "preview":
            processed = self.fallback.process_for_preview(frame_packet)
        else:
            processed = self.fallback.process_for_save(frame_packet)
        processed.meta.update({
            "engine": self.actual_name,
            "requested_engine": self.requested_name,
            "mode_tag": self.mode_tag,
            "fallback": True,
            "fallback_reason": reason,
            "last_error": reason,
            "rga_active_calls": self.active_calls,
            "rga_fallback_calls": self.fallback_calls,
        })
        return processed

    def _run_rga(self, frame_packet: FramePacket, dst_w: int, dst_h: int, rotate_code: int):
        import numpy as np

        if self.lib is None or not self.wrapper_available:
            raise RuntimeError(self.load_error or "RGA wrapper unavailable")
        valid, reason = self._validate_native_call(frame_packet, dst_w, dst_h)
        if not valid:
            raise ValueError(reason)
        src = self._nv12_view(frame_packet)
        dst = np.empty((int(dst_h), int(dst_w), 3), dtype=np.uint8)
        src_ptr = src.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte))
        dst_ptr = dst.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte))
        ret = self.lib.myui_rga_nv12_to_bgr(
            src_ptr,
            int(frame_packet.width),
            int(frame_packet.height),
            dst_ptr,
            int(dst_w),
            int(dst_h),
            int(rotate_code),
        )
        if ret != 0:
            native_error = self._native_last_error(self.lib)
            self.last_native_message = native_error
            raise RuntimeError(f"myui_rga_nv12_to_bgr ret={ret} {native_error}")
        self.last_native_message = self._native_last_error(self.lib)
        return dst

    @staticmethod
    def _cpu_rotate_bgr(bgr_image, rotate_code: int):
        import cv2

        if rotate_code == 1:
            return cv2.rotate(bgr_image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if rotate_code == 2:
            return cv2.rotate(bgr_image, cv2.ROTATE_90_CLOCKWISE)
        if rotate_code == 3:
            return cv2.rotate(bgr_image, cv2.ROTATE_180)
        return bgr_image

    def _run_rga_preprocess(self, frame_packet: FramePacket, dst_w: int, dst_h: int, rotate_code: int):
        if rotate_code == 0:
            t0 = time.perf_counter()
            image = self._run_rga(frame_packet, dst_w, dst_h, rotate_code)
            return image, {
                "rga_transform": "convert",
                "post_rotate_cpu": False,
                "native_success_detail": self.last_native_message,
                "rga_convert_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            }
        try:
            t0 = time.perf_counter()
            image = self._run_rga(frame_packet, dst_w, dst_h, rotate_code)
            return image, {
                "rga_transform": "convert_rotate",
                "post_rotate_cpu": False,
                "native_success_detail": self.last_native_message,
                "rga_convert_rotate_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            }
        except Exception as first_exc:
            try:
                t_convert = time.perf_counter()
                bgr = self._run_rga(frame_packet, int(frame_packet.width), int(frame_packet.height), 0)
                convert_ms = round((time.perf_counter() - t_convert) * 1000.0, 3)
            except Exception as second_exc:
                raise RuntimeError(f"RGA transform failed: {first_exc}; RGA convert-only failed: {second_exc}")
            log_event(
                "preprocess",
                "requested=rga actual=rga_active transform=convert_only_cpu_rotate "
                f"reason=native_rotate_failed:{first_exc}",
            )
            t_rotate = time.perf_counter()
            rotated = self._cpu_rotate_bgr(bgr, rotate_code)
            rotate_ms = round((time.perf_counter() - t_rotate) * 1000.0, 3)
            return rotated, {
                "rga_transform": "convert_only_cpu_rotate",
                "post_rotate_cpu": True,
                "native_transform_error": str(first_exc),
                "native_success_detail": self.last_native_message,
                "rga_convert_ms": convert_ms,
                "cpu_rotate_ms": rotate_ms,
            }

    def _run_rga_preview_pre_scaled(self, frame_packet: FramePacket, preview_w: int, preview_h: int, rotate_code: int):
        if rotate_code not in (1, 2):
            raise ValueError("pre-scaled preview path is only for 90-degree rotation")
        pre_rotate_w = int(preview_h)
        pre_rotate_h = int(preview_w)
        t_convert = time.perf_counter()
        bgr_small = self._run_rga(frame_packet, pre_rotate_w, pre_rotate_h, 0)
        convert_ms = round((time.perf_counter() - t_convert) * 1000.0, 3)
        t_rotate = time.perf_counter()
        preview_image = self._cpu_rotate_bgr(bgr_small, rotate_code)
        rotate_ms = round((time.perf_counter() - t_rotate) * 1000.0, 3)
        return preview_image, {
            "rga_transform": "convert_resize_only_cpu_rotate",
            "post_rotate_cpu": True,
            "native_success_detail": self.last_native_message,
            "rga_convert_ms": convert_ms,
            "cpu_rotate_ms": rotate_ms,
            "preview_pre_scaled": True,
            "preview_pre_rotate_width": pre_rotate_w,
            "preview_pre_rotate_height": pre_rotate_h,
        }

    def _processed(
        self,
        frame_packet: FramePacket,
        bgr_image,
        preview_jpeg: bytes,
        purpose: str,
        extra_meta: Dict[str, Any] | None = None,
    ) -> ProcessedFrame:
        height, width = bgr_image.shape[:2]
        self._mark_active(f"ok: {purpose} {frame_packet.width}x{frame_packet.height}->{width}x{height}")
        meta = {
            "engine": "rga",
            "requested_engine": self.requested_name,
            "mode_tag": "rga_active",
            "fallback": False,
            "purpose": purpose,
            "rotation": self.rotation,
            "source_pixel_format": frame_packet.pixel_format,
            "rga_lib": self.lib_path,
            "rga_version": self.lib_version,
            "rga_active_calls": self.active_calls,
            "rga_fallback_calls": self.fallback_calls,
            "last_error": "ok",
            "native_last_message": self.last_native_message,
            "stride_w": int(frame_packet.stride_w or frame_packet.width),
            "stride_h": int(frame_packet.stride_h or frame_packet.height),
            "stride_inferred": bool(frame_packet.stride_inferred),
        }
        if extra_meta:
            meta.update(extra_meta)
        return ProcessedFrame(
            seq=frame_packet.seq,
            timestamp=frame_packet.timestamp,
            width=int(width),
            height=int(height),
            bgr_image=bgr_image,
            preview_jpeg=preview_jpeg,
            meta=meta,
        )

    def _can_try_rga(self, frame_packet: FramePacket) -> Tuple[bool, str]:
        fmt = (frame_packet.pixel_format or "").upper()
        if fmt != "NV12":
            return False, f"input pixel_format={fmt or 'unknown'}; RGA wrapper currently supports NV12 only"
        if not self.wrapper_available:
            return False, self.load_error or self.reason
        return True, ""

    def process_for_preview(self, frame_packet: FramePacket) -> ProcessedFrame:
        import cv2

        ok, reason = self._can_try_rga(frame_packet)
        if not ok:
            return self._fallback_processed(frame_packet, "preview", reason)
        rotate_code = self._rotation_code(self.rotation)
        full_w, full_h = self._rotated_dimensions(frame_packet.width, frame_packet.height, rotate_code)
        try:
            t_total = time.perf_counter()
            preview_w, preview_h = self._preview_dimensions(full_w, full_h)
            if rotate_code in (1, 2) and (preview_w, preview_h) != (full_w, full_h):
                preview_image, transform_meta = self._run_rga_preview_pre_scaled(frame_packet, preview_w, preview_h, rotate_code)
                bgr = preview_image
            else:
                bgr, transform_meta = self._run_rga_preprocess(frame_packet, full_w, full_h, rotate_code)
                preview_image = bgr
            resize_ms = 0.0
            if not transform_meta.get("preview_pre_scaled") and (preview_w, preview_h) != (full_w, full_h):
                t_resize = time.perf_counter()
                preview_image = cv2.resize(bgr, (preview_w, preview_h), interpolation=cv2.INTER_AREA)
                resize_ms = (time.perf_counter() - t_resize) * 1000.0
            encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(self.preview_jpeg_quality)]
            t_encode = time.perf_counter()
            ok_encode, encoded = cv2.imencode(".jpg", preview_image, encode_params)
            encode_ms = (time.perf_counter() - t_encode) * 1000.0
            preview_jpeg = encoded.tobytes() if ok_encode else b""
            transform_meta.update({
                "preview_resize_ms": round(resize_ms, 3),
                "preview_jpeg_encode_ms": round(encode_ms, 3),
                "preview_total_ms": round((time.perf_counter() - t_total) * 1000.0, 3),
            })
            return self._processed(frame_packet, bgr, preview_jpeg, "preview", transform_meta)
        except Exception as exc:
            return self._fallback_processed(frame_packet, "preview", f"RGA call failed: {exc}")

    def process_for_save(self, frame_packet: FramePacket) -> ProcessedFrame:
        ok, reason = self._can_try_rga(frame_packet)
        if not ok:
            return self._fallback_processed(frame_packet, "save", reason)
        rotate_code = self._rotation_code(self.rotation)
        dst_w, dst_h = self._rotated_dimensions(frame_packet.width, frame_packet.height, rotate_code)
        try:
            t_total = time.perf_counter()
            bgr, transform_meta = self._run_rga_preprocess(frame_packet, dst_w, dst_h, rotate_code)
            transform_meta.update({
                "save_total_ms": round((time.perf_counter() - t_total) * 1000.0, 3),
            })
            return self._processed(frame_packet, bgr, b"", "save", transform_meta)
        except Exception as exc:
            return self._fallback_processed(frame_packet, "save", f"RGA call failed: {exc}")

    def status(self) -> Dict[str, Any]:
        fallback = self.mode_tag == "rga_fallback_cpu"
        return {
            "requested": self.requested_name,
            "actual": self.actual_name,
            "mode_tag": self.mode_tag,
            "available": bool(self.wrapper_available),
            "fallback": fallback,
            "reason": self.last_reason,
            "last_error": self.last_error,
            "require_rga": bool(self.require_rga),
            "probe": self.probe,
            "lib_path": self.lib_path,
            "lib_version": self.lib_version,
            "candidate_paths": self.candidate_paths,
            "load_error": self.load_error,
            "wrapper_available": bool(self.wrapper_available),
            "active_calls": int(self.active_calls),
            "fallback_calls": int(self.fallback_calls),
            "fallback_engine": self.fallback.status(),
        }
