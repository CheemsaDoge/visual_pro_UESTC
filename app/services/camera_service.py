#!/usr/bin/env python3
"""Camera session service.

This module keeps the old API behavior while routing all preview/save work
through PreprocessEngine and all auto-save decisions through KeyframeSelector.
"""
from __future__ import annotations

import copy
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any, List, Tuple
from urllib.parse import quote

from app import config
from app.capture.gst_capture import build_nv12_to_bgr_pipeline
from app.capture.gst_raw_nv12_capture import GstRawNv12Capture, OpenCvGstRawNv12Capture
from app.capture.v4l2_capture import V4L2CtlNv12Capture
from app.schemas import FramePacket, ProcessedFrame
from app.services.keyframe_service import get_selector, get_selector_status
from app.services.preprocess_service import get_preprocess_engine, get_preprocess_status
from app.services.storage_service import camera_capture_file_item
from app.services.stitch_service import run_image_stitch
from app.utils.log import log_event

CAMERA_RUNTIME_LOCK = threading.Lock()
CAMERA_RUNTIME = {
    "active": False,
    "mode": "",
    "session_id": "",
    "started_at": 0.0,
    "stopped_at": 0.0,
    "capture_files": [],
    "capture_count": 0,
    "last_capture_name": "",
    "last_capture_mtime": 0,
    "last_frame_jpeg": b"",
    "last_frame_raw": None,
    "last_frame_packet": None,
    "last_frame_mtime": 0.0,
    "latest_frame_seq": 0,
    "latest_frame_mtime": 0.0,
    "preview_frame_seq": 0,
    "error": "",
    "stop_event": None,
    "thread": None,
    "preview_thread": None,
    "last_result": {},
    "open_source": "",
    "open_attempts": [],
    "capture_backend": "",
    "require_rga": False,
    "last_frame_format": "",
    "last_frame_width": 0,
    "last_frame_height": 0,
    "last_frame_buffer_size": 0,
    "last_frame_stride_w": 0,
    "last_frame_stride_h": 0,
    "last_frame_stride_inferred": False,
    "last_preview_preprocess": {},
    "last_save_preprocess": {},
    "last_keep_ts": 0.0,
    "last_keep_image": None,
    "last_selector_decision": {},
    "dropped_count": 0,
}

CAMERA_DEVICE_HINTS = (
    "/dev/video-camera0",
    "/dev/video44",
    "/dev/video22",
    "/dev/video31",
    "/dev/video62",
)


def _camera_source_display(value: Any) -> str:
    return str(value)


def _camera_read_timeout_sec() -> float:
    if config.camera_effective_width() >= 3000 or config.camera_effective_height() >= 2000:
        return 8.0
    return 5.0


def _camera_add_candidate(candidates: List[str], seen: set[str], device: str | None) -> None:
    if not device:
        return
    path = str(device).strip()
    if not path or path in seen:
        return
    seen.add(path)
    candidates.append(path)


def _discover_rkisp_mainpath_devices() -> List[str]:
    if not shutil.which("v4l2-ctl"):
        return []
    try:
        raw = subprocess.check_output(["v4l2-ctl", "--list-devices"], stderr=subprocess.STDOUT, text=True, timeout=4)
    except Exception:
        return []
    devices: List[str] = []
    in_mainpath = False
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            in_mainpath = False
            continue
        if not line.startswith("\t"):
            in_mainpath = "rkisp_mainpath" in stripped
            continue
        if in_mainpath and stripped.startswith("/dev/video"):
            devices.append(stripped)
    return devices


def _camera_device_candidates(prefer_existing: bool = False) -> List[str]:
    candidates: List[str] = []
    seen: set[str] = set()
    configured = config.camera_device_path()
    _camera_add_candidate(candidates, seen, configured)
    if configured and os.path.islink(configured):
        _camera_add_candidate(candidates, seen, os.path.realpath(configured))
    for device in _discover_rkisp_mainpath_devices():
        _camera_add_candidate(candidates, seen, device)
    for device in CAMERA_DEVICE_HINTS:
        _camera_add_candidate(candidates, seen, device)
        if os.path.islink(device):
            _camera_add_candidate(candidates, seen, os.path.realpath(device))
    if prefer_existing:
        existing = [device for device in candidates if os.path.exists(device)]
        return existing or candidates
    return candidates


def _camera_primary_device() -> str:
    candidates = _camera_device_candidates(prefer_existing=True)
    if candidates:
        return candidates[0]
    return config.camera_device_path() or "/dev/video-camera0"


def _camera_gst_pipeline(device: str | None = None) -> str:
    dev = device or _camera_primary_device()
    return build_nv12_to_bgr_pipeline(
        dev,
        config.camera_effective_width(),
        config.camera_effective_height(),
        config.camera_effective_fps(),
        config.CAMERA_PIXEL_FORMAT,
    )


def _camera_open_candidates(cv2) -> List[Tuple[Any, Any, str]]:
    cap_v4l2 = getattr(cv2, "CAP_V4L2", None)
    cap_gst = getattr(cv2, "CAP_GSTREAMER", None)
    candidates: List[Tuple[Any, Any, str]] = []
    seen = set()
    device_candidates = _camera_device_candidates(prefer_existing=True)

    def add(source: Any, api: Any = None, note: str = "") -> None:
        key = (repr(source), int(api) if isinstance(api, int) else api)
        if key in seen:
            return
        seen.add(key)
        candidates.append((source, api, note))

    source = config.CAMERA_SOURCE
    source_str = (str(source).strip() if source is not None else "").strip()
    source_num = None
    if isinstance(source, int):
        source_num = source
    elif re.fullmatch(r"-?\d+", source_str):
        try:
            source_num = int(source_str)
        except Exception:
            source_num = None

    if source_num is not None:
        if source_num >= 0 and config.CAMERA_BACKEND in ("auto", "gstreamer"):
            add(_camera_gst_pipeline(f"/dev/video{source_num}"), cap_gst, "config-gst-nv12")
        if config.CAMERA_BACKEND == "opencv":
            add(source_num, None, "config-index")
            if source_num >= 0:
                add(f"/dev/video{source_num}", cap_v4l2, "config-index-dev-v4l2")
                add(f"/dev/video{source_num}", None, "config-index-dev-default")
    else:
        if source_str.startswith("gst:"):
            pipeline = source_str[4:].strip()
            if pipeline:
                add(pipeline, cap_gst, "config-gst-prefix")
        elif "!" in source_str:
            add(source_str, cap_gst, "config-gst-pipeline")
        if source_str.startswith("/dev/video"):
            if config.CAMERA_BACKEND in ("auto", "gstreamer"):
                add(_camera_gst_pipeline(source_str), cap_gst, "config-gst-nv12")
            if config.CAMERA_BACKEND in ("auto", "opencv"):
                add(source_str, cap_v4l2, "config-dev-v4l2")
                add(source_str, None, "config-dev-default")
        if source_str and config.CAMERA_BACKEND == "opencv":
            add(source_str, None, "config-default")

    for dev in device_candidates:
        if config.CAMERA_BACKEND in ("auto", "gstreamer"):
            add(_camera_gst_pipeline(dev), cap_gst, f"fallback-gst-{os.path.basename(dev)}-nv12")
        if config.CAMERA_BACKEND in ("auto", "opencv"):
            add(dev, cap_v4l2, "fallback-dev-v4l2")
            add(dev, None, "fallback-dev-default")
    return candidates


def _try_open_gst_raw_capture(cv2, device: str, attempts: List[str]):
    try:
        cap = OpenCvGstRawNv12Capture(
            cv2=cv2,
            device=device,
            width=config.camera_effective_width(),
            height=config.camera_effective_height(),
            fps=config.camera_effective_fps(),
            pixel_format=config.CAMERA_PIXEL_FORMAT,
            timeout_sec=_camera_read_timeout_sec(),
        )
        opened = bool(cap.isOpened())
        detail = getattr(cap, "last_error", "") or "ready"
        attempts.append(
            f"gst-opencv-nv12-raw:{device} {config.CAMERA_PIXEL_FORMAT} "
            f"{config.camera_effective_width()}x{config.camera_effective_height()} "
            f"{'ok' if opened else 'failed'} {detail}"
        )
        if opened:
            return cap, f"gst-opencv-nv12-raw:{device}"
        cap.release()
    except Exception as exc:
        attempts.append(f"gst-opencv-nv12-raw:{device} exception={exc}")
    try:
        cap = GstRawNv12Capture(
            device=device,
            width=config.camera_effective_width(),
            height=config.camera_effective_height(),
            fps=config.camera_effective_fps(),
            pixel_format=config.CAMERA_PIXEL_FORMAT,
            timeout_sec=_camera_read_timeout_sec(),
        )
        opened = bool(cap.isOpened())
        detail = getattr(cap, "last_error", "") or "ready"
        attempts.append(
            f"gst-nv12-raw:{device} {config.CAMERA_PIXEL_FORMAT} "
            f"{config.camera_effective_width()}x{config.camera_effective_height()} "
            f"{'ok' if opened else 'failed'} {detail}"
        )
        if opened:
            return cap, f"gst-gi-nv12-raw:{device}"
        cap.release()
    except Exception as exc:
        attempts.append(f"gst-gi-nv12-raw:{device} exception={exc}")
    return None, ""


def _try_open_v4l2_raw_capture(cv2, device: str, attempts: List[str]):
    try:
        cap = V4L2CtlNv12Capture(
            cv2,
            device,
            config.camera_effective_width(),
            config.camera_effective_height(),
            config.camera_effective_fps(),
            config.CAMERA_PIXEL_FORMAT,
            config.CAMERA_V4L2_BUFFER_COUNT,
            timeout_sec=_camera_read_timeout_sec(),
            raw_packet=True,
        )
        opened = bool(cap.isOpened())
        detail = getattr(cap, "last_error", "") or "ready"
        attempts.append(
            f"v4l2ctl-nv12-raw:{device} {config.CAMERA_PIXEL_FORMAT} "
            f"{config.camera_effective_width()}x{config.camera_effective_height()} "
            f"{'ok' if opened else 'failed'} {detail}"
        )
        if opened:
            return cap, f"v4l2ctl-nv12-raw:{device}"
        cap.release()
    except Exception as exc:
        attempts.append(f"v4l2ctl-nv12-raw:{device} exception={exc}")
    return None, ""


def _open_camera_capture(cv2, capture_backend: str):
    attempts = []
    raw_devices = _camera_device_candidates(prefer_existing=True)
    if capture_backend in ("auto_raw", "gst_nv12_raw"):
        for device in raw_devices:
            cap, opened_source = _try_open_gst_raw_capture(cv2, device, attempts)
            if cap is not None and opened_source:
                return cap, opened_source, attempts
        if capture_backend == "gst_nv12_raw":
            return None, "", attempts

    if capture_backend in ("auto_raw", "v4l2ctl_nv12_raw"):
        for device in raw_devices:
            cap, opened_source = _try_open_v4l2_raw_capture(cv2, device, attempts)
            if cap is not None and opened_source:
                return cap, opened_source, attempts
        if capture_backend == "v4l2ctl_nv12_raw":
            return None, "", attempts

    if config.CAMERA_BACKEND in ("auto", "gstreamer", "opencv"):
        for source, api, note in _camera_open_candidates(cv2):
            if config.CAMERA_BACKEND == "gstreamer" and "gst" not in note:
                continue
            if config.CAMERA_BACKEND == "opencv" and "gst" in note:
                continue
            cap = None
            api_name = "default"
            if api is not None:
                if api == getattr(cv2, "CAP_V4L2", None):
                    api_name = "CAP_V4L2"
                elif api == getattr(cv2, "CAP_GSTREAMER", None):
                    api_name = "CAP_GSTREAMER"
                else:
                    api_name = str(api)
            try:
                cap = cv2.VideoCapture(source) if api is None else cv2.VideoCapture(source, api)
                opened = bool(cap is not None and cap.isOpened())
            except Exception as exc:
                opened = False
                attempts.append(f"{note}:{_camera_source_display(source)} via {api_name} exception={exc}")
            else:
                attempts.append(f"{note}:{_camera_source_display(source)} via {api_name} {'ok' if opened else 'failed'}")
            if opened:
                return cap, _camera_source_display(source), attempts
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

    if config.CAMERA_BACKEND in ("auto", "v4l2ctl"):
        for device in raw_devices:
            try:
                cap = V4L2CtlNv12Capture(
                    cv2,
                    device,
                    config.camera_effective_width(),
                    config.camera_effective_height(),
                    config.camera_effective_fps(),
                    config.CAMERA_PIXEL_FORMAT,
                    config.CAMERA_V4L2_BUFFER_COUNT,
                    timeout_sec=_camera_read_timeout_sec(),
                )
                opened = bool(cap.isOpened())
                detail = getattr(cap, "last_error", "") or "ready"
                attempts.append(
                    f"v4l2ctl-nv12:{device} {config.CAMERA_PIXEL_FORMAT} "
                    f"{config.camera_effective_width()}x{config.camera_effective_height()} "
                    f"{'ok' if opened else 'failed'} {detail}"
                )
                if opened:
                    return cap, f"v4l2-ctl:{device}", attempts
                cap.release()
            except Exception as exc:
                attempts.append(f"v4l2ctl-nv12:{device} exception={exc}")
    return None, "", attempts


def _packet_from_frame(frame, seq: int, timestamp: float, source: str) -> FramePacket:
    if isinstance(frame, FramePacket):
        return FramePacket(
            seq=seq,
            timestamp=timestamp,
            width=frame.width,
            height=frame.height,
            pixel_format=frame.pixel_format,
            source=frame.source or source,
            data=frame.data,
            meta=copy.deepcopy(frame.meta),
            stride_w=frame.stride_w,
            stride_h=frame.stride_h,
            timestamp_ns=frame.timestamp_ns or int(timestamp * 1000000000),
            buffer_size=frame.buffer_size,
            stride_inferred=frame.stride_inferred,
        )
    try:
        height, width = frame.shape[:2]
    except Exception:
        height, width = 0, 0
    # Current adapters deliver BGR frames to Python.  RGA can later move this
    # boundary earlier and pass raw NV12 FramePacket data instead.
    return FramePacket(
        seq=seq,
        timestamp=timestamp,
        width=int(width),
        height=int(height),
        pixel_format="BGR",
        source=source,
        data=frame,
        stride_w=int(width),
        stride_h=int(height),
    )


def _copy_frame_packet(packet: FramePacket, timestamp: float) -> FramePacket:
    data = packet.data
    if hasattr(data, "copy"):
        data = data.copy()
    elif isinstance(data, bytearray):
        data = bytes(data)
    return FramePacket(
        seq=packet.seq,
        timestamp=timestamp,
        width=packet.width,
        height=packet.height,
        pixel_format=packet.pixel_format,
        source=packet.source,
        data=data,
        meta=copy.deepcopy(packet.meta),
        stride_w=packet.stride_w,
        stride_h=packet.stride_h,
        timestamp_ns=int(timestamp * 1000000000),
        buffer_size=packet.buffer_size,
        stride_inferred=packet.stride_inferred,
    )


def _preprocess_last_error(processed: ProcessedFrame | None = None) -> str:
    if processed is not None and processed.meta.get("last_error"):
        return str(processed.meta.get("last_error"))
    status = get_preprocess_status()
    return str(status.get("last_error") or status.get("reason") or "")


def _log_camera_preprocess_result(kind: str, capture_backend: str, processed: ProcessedFrame) -> None:
    status = get_preprocess_status()
    mode = processed.meta.get("mode_tag") or status.get("mode_tag") or ""
    active_calls = int(processed.meta.get("rga_active_calls", status.get("active_calls", 0)) or 0)
    fallback_calls = int(processed.meta.get("rga_fallback_calls", status.get("fallback_calls", 0)) or 0)
    last_error = _preprocess_last_error(processed)
    log_event(
        "camera",
        f"{kind}.capture_backend={capture_backend} "
        f"{kind}.preprocess_mode={mode} "
        f"{kind}.rga_active_calls={active_calls} "
        f"{kind}.rga_fallback_calls={fallback_calls} "
        f"{kind}.last_error={last_error}",
    )
    with CAMERA_RUNTIME_LOCK:
        key = "last_preview_preprocess" if kind == "preview" else "last_save_preprocess"
        CAMERA_RUNTIME[key] = {
            "capture_backend": capture_backend,
            "preprocess_mode": mode,
            "rga_active_calls": active_calls,
            "rga_fallback_calls": fallback_calls,
            "last_error": last_error,
            "source_pixel_format": processed.meta.get("source_pixel_format", ""),
            "fallback": bool(processed.meta.get("fallback", False)),
            "rga_transform": processed.meta.get("rga_transform", ""),
            "post_rotate_cpu": bool(processed.meta.get("post_rotate_cpu", False)),
            "native_transform_error": processed.meta.get("native_transform_error", ""),
            "rga_convert_ms": processed.meta.get("rga_convert_ms"),
            "rga_convert_rotate_ms": processed.meta.get("rga_convert_rotate_ms"),
            "cpu_rotate_ms": processed.meta.get("cpu_rotate_ms"),
            "preview_pre_scaled": bool(processed.meta.get("preview_pre_scaled", False)),
            "preview_pre_rotate_width": processed.meta.get("preview_pre_rotate_width"),
            "preview_pre_rotate_height": processed.meta.get("preview_pre_rotate_height"),
            "preview_resize_ms": processed.meta.get("preview_resize_ms"),
            "preview_jpeg_encode_ms": processed.meta.get("preview_jpeg_encode_ms"),
            "preview_total_ms": processed.meta.get("preview_total_ms"),
            "save_total_ms": processed.meta.get("save_total_ms"),
        }


def _enforce_required_rga(kind: str, capture_backend: str, processed: ProcessedFrame, require_rga: bool) -> None:
    _log_camera_preprocess_result(kind, capture_backend, processed)
    if require_rga and processed.meta.get("mode_tag") != "rga_active":
        raise RuntimeError(f"{kind} require_rga failed: preprocess_mode={processed.meta.get('mode_tag')}")


def get_camera_backend_status() -> dict:
    device_candidates = _camera_device_candidates(prefer_existing=False)
    info = {
        "ok": True,
        "enabled": False,
        "backend": config.CAMERA_BACKEND,
        "capture_backend": config.CAMERA_CAPTURE_BACKEND,
        "source": config.CAMERA_SOURCE,
        "source_text": config.camera_source_text(),
        "device": _camera_primary_device(),
        "device_candidates": device_candidates,
        "pixel_format": config.CAMERA_PIXEL_FORMAT,
        "rotation": config.CAMERA_ROTATION,
        "frame_width": config.CAMERA_FRAME_WIDTH,
        "frame_height": config.CAMERA_FRAME_HEIGHT,
        "effective_width": config.camera_effective_width(),
        "effective_height": config.camera_effective_height(),
        "fps": config.CAMERA_TARGET_FPS,
        "preview_max_dim": config.CAMERA_PREVIEW_MAX_DIM,
        "preview_jpeg_quality": config.CAMERA_PREVIEW_JPEG_QUALITY,
        "preview_fps": config.CAMERA_PREVIEW_FPS,
        "auto_interval_sec": config.CAMERA_AUTO_INTERVAL_SEC,
        "preprocess": get_preprocess_status(),
        "selector": get_selector_status(),
    }
    try:
        import cv2

        info["enabled"] = True
        info["opencv"] = getattr(cv2, "__version__", "unknown")
    except Exception as exc:
        info["msg"] = f"opencv unavailable: {exc}"
    return info


def _camera_runtime_snapshot() -> dict:
    with CAMERA_RUNTIME_LOCK:
        return {
            "active": bool(CAMERA_RUNTIME.get("active")),
            "mode": CAMERA_RUNTIME.get("mode") or "",
            "session_id": CAMERA_RUNTIME.get("session_id") or "",
            "started_at": float(CAMERA_RUNTIME.get("started_at") or 0.0),
            "stopped_at": float(CAMERA_RUNTIME.get("stopped_at") or 0.0),
            "capture_count": int(CAMERA_RUNTIME.get("capture_count") or 0),
            "capture_files": list(CAMERA_RUNTIME.get("capture_files") or []),
            "last_capture_name": CAMERA_RUNTIME.get("last_capture_name") or "",
            "last_capture_mtime": int(CAMERA_RUNTIME.get("last_capture_mtime") or 0),
            "last_frame_ready": bool(CAMERA_RUNTIME.get("last_frame_jpeg")),
            "last_frame_mtime": float(CAMERA_RUNTIME.get("last_frame_mtime") or 0.0),
            "latest_frame_seq": int(CAMERA_RUNTIME.get("latest_frame_seq") or 0),
            "latest_frame_mtime": float(CAMERA_RUNTIME.get("latest_frame_mtime") or 0.0),
            "preview_frame_seq": int(CAMERA_RUNTIME.get("preview_frame_seq") or 0),
            "error": CAMERA_RUNTIME.get("error") or "",
            "last_result": copy.deepcopy(CAMERA_RUNTIME.get("last_result") or {}),
            "open_source": CAMERA_RUNTIME.get("open_source") or "",
            "open_attempts": list(CAMERA_RUNTIME.get("open_attempts") or []),
            "capture_backend": CAMERA_RUNTIME.get("capture_backend") or "",
            "require_rga": bool(CAMERA_RUNTIME.get("require_rga")),
            "last_frame_format": CAMERA_RUNTIME.get("last_frame_format") or "",
            "last_frame_width": int(CAMERA_RUNTIME.get("last_frame_width") or 0),
            "last_frame_height": int(CAMERA_RUNTIME.get("last_frame_height") or 0),
            "last_frame_buffer_size": int(CAMERA_RUNTIME.get("last_frame_buffer_size") or 0),
            "last_frame_stride_w": int(CAMERA_RUNTIME.get("last_frame_stride_w") or 0),
            "last_frame_stride_h": int(CAMERA_RUNTIME.get("last_frame_stride_h") or 0),
            "last_frame_stride_inferred": bool(CAMERA_RUNTIME.get("last_frame_stride_inferred")),
            "last_preview_preprocess": copy.deepcopy(CAMERA_RUNTIME.get("last_preview_preprocess") or {}),
            "last_save_preprocess": copy.deepcopy(CAMERA_RUNTIME.get("last_save_preprocess") or {}),
            "last_selector_decision": copy.deepcopy(CAMERA_RUNTIME.get("last_selector_decision") or {}),
            "dropped_count": int(CAMERA_RUNTIME.get("dropped_count") or 0),
        }


def get_camera_session_status() -> dict:
    backend = get_camera_backend_status()
    snap = _camera_runtime_snapshot()
    data = {
        "ok": True,
        "enabled": backend.get("enabled", False),
        "backend": backend.get("backend"),
        "capture_backend": snap.get("capture_backend") or backend.get("capture_backend"),
        "source": backend.get("source"),
        "source_text": backend.get("source_text"),
        "device": backend.get("device"),
        "device_candidates": backend.get("device_candidates") or [],
        "pixel_format": backend.get("pixel_format"),
        "rotation": backend.get("rotation"),
        "frame_width": backend.get("frame_width"),
        "frame_height": backend.get("frame_height"),
        "fps": backend.get("fps"),
        "preview_max_dim": backend.get("preview_max_dim"),
        "preview_jpeg_quality": backend.get("preview_jpeg_quality"),
        "preview_fps": backend.get("preview_fps"),
        "auto_interval_sec": backend.get("auto_interval_sec"),
        "preprocess": backend.get("preprocess"),
        "selector": backend.get("selector"),
        "active": snap.get("active", False),
        "mode": snap.get("mode"),
        "session_id": snap.get("session_id"),
        "started_at": snap.get("started_at"),
        "stopped_at": snap.get("stopped_at"),
        "capture_count": snap.get("capture_count"),
        "last_capture_name": snap.get("last_capture_name"),
        "last_capture_mtime": snap.get("last_capture_mtime"),
        "last_frame_ready": snap.get("last_frame_ready"),
        "last_frame_mtime": snap.get("last_frame_mtime"),
        "latest_frame_seq": snap.get("latest_frame_seq"),
        "latest_frame_mtime": snap.get("latest_frame_mtime"),
        "preview_frame_seq": snap.get("preview_frame_seq"),
        "error": snap.get("error") or backend.get("msg", ""),
        "last_result": snap.get("last_result"),
        "open_source": snap.get("open_source"),
        "require_rga": snap.get("require_rga"),
        "last_frame_format": snap.get("last_frame_format"),
        "last_frame_width": snap.get("last_frame_width"),
        "last_frame_height": snap.get("last_frame_height"),
        "last_frame_buffer_size": snap.get("last_frame_buffer_size"),
        "last_frame_stride_w": snap.get("last_frame_stride_w"),
        "last_frame_stride_h": snap.get("last_frame_stride_h"),
        "last_frame_stride_inferred": snap.get("last_frame_stride_inferred"),
        "last_preview_preprocess": snap.get("last_preview_preprocess"),
        "last_save_preprocess": snap.get("last_save_preprocess"),
        "last_selector_decision": snap.get("last_selector_decision"),
        "dropped_count": snap.get("dropped_count"),
    }
    if backend.get("opencv"):
        data["opencv"] = backend.get("opencv")
    if backend.get("msg") and not backend.get("enabled"):
        data["msg"] = backend.get("msg")
    return data


def _save_processed_frame(processed: ProcessedFrame, session_id: str, frame_index: int, selector_decision: dict | None = None):
    import cv2

    filename = f"camera_{session_id}_{frame_index:04d}.jpg"
    path = os.path.join(config.STITCH_INPUT_DIR, filename)
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(config.CAMERA_JPEG_QUALITY)]
    if not cv2.imwrite(path, processed.bgr_image, encode_params):
        return None, "failed to save camera frame"
    try:
        item = camera_capture_file_item(filename)
    except Exception as exc:
        return None, f"failed to stat camera frame: {exc}"
    with CAMERA_RUNTIME_LOCK:
        if CAMERA_RUNTIME.get("session_id") != session_id:
            return item, ""
        CAMERA_RUNTIME["capture_files"].append(filename)
        CAMERA_RUNTIME["capture_count"] = len(CAMERA_RUNTIME["capture_files"])
        CAMERA_RUNTIME["last_capture_name"] = filename
        CAMERA_RUNTIME["last_capture_mtime"] = item.get("mtime") or int(time.time())
        CAMERA_RUNTIME["last_keep_ts"] = processed.timestamp
        CAMERA_RUNTIME["last_keep_image"] = processed.bgr_image.copy()
        if selector_decision is not None:
            CAMERA_RUNTIME["last_selector_decision"] = copy.deepcopy(selector_decision)
    return item, ""


def _selector_context() -> dict:
    with CAMERA_RUNTIME_LOCK:
        return {
            "last_keep_ts": float(CAMERA_RUNTIME.get("last_keep_ts") or 0.0),
            "last_keep_image": CAMERA_RUNTIME.get("last_keep_image"),
            "capture_count": int(CAMERA_RUNTIME.get("capture_count") or 0),
        }


def _camera_capture_loop(session_id: str, mode: str, stop_event: threading.Event, capture_backend: str, require_rga: bool) -> None:
    cap = None
    try:
        import cv2

        cap, opened_source, open_attempts = _open_camera_capture(cv2, capture_backend)
        if cap is None or not cap.isOpened():
            attempt_msg = " | ".join(open_attempts[-6:]) if open_attempts else "no attempts"
            with CAMERA_RUNTIME_LOCK:
                if CAMERA_RUNTIME.get("session_id") == session_id:
                    CAMERA_RUNTIME["active"] = False
                    CAMERA_RUNTIME["open_source"] = ""
                    CAMERA_RUNTIME["open_attempts"] = list(open_attempts)
                    CAMERA_RUNTIME["error"] = f"cannot open camera source: {config.camera_source_text()} candidates={','.join(_camera_device_candidates(prefer_existing=True)[:6])} ({attempt_msg})"
            return

        with CAMERA_RUNTIME_LOCK:
            if CAMERA_RUNTIME.get("session_id") == session_id:
                CAMERA_RUNTIME["open_source"] = opened_source
                CAMERA_RUNTIME["open_attempts"] = list(open_attempts)

        opened_source_text = str(opened_source or "")
        fixed_format_source = (
            ("v4l2src" in opened_source_text and "appsink" in opened_source_text)
            or opened_source_text.startswith("v4l2-ctl:")
            or opened_source_text.startswith("v4l2ctl-nv12-raw:")
            or opened_source_text.startswith("gst-nv12-raw:")
            or opened_source_text.startswith("gst-opencv-nv12-raw:")
            or opened_source_text.startswith("gst-gi-nv12-raw:")
        )
        if not fixed_format_source:
            if config.CAMERA_FRAME_WIDTH > 0:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_FRAME_WIDTH)
            if config.CAMERA_FRAME_HEIGHT > 0:
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_FRAME_HEIGHT)
            if config.CAMERA_TARGET_FPS > 0:
                cap.set(cv2.CAP_PROP_FPS, config.CAMERA_TARGET_FPS)
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

        next_auto_time = time.time()
        first_frame_deadline = time.time() + _camera_read_timeout_sec() + 1.0
        got_frame = False
        read_failures = 0
        while not stop_event.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                read_failures += 1
                last_error = getattr(cap, "last_error", "") or "empty frame"
                now = time.time()
                if "short NV12 frame" in last_error or "empty NV12 frame" in last_error:
                    with CAMERA_RUNTIME_LOCK:
                        if CAMERA_RUNTIME.get("session_id") == session_id:
                            CAMERA_RUNTIME["error"] = f"camera read failed from {opened_source}: {last_error}"
                    break
                if (not got_frame and now >= first_frame_deadline) or read_failures >= 60:
                    with CAMERA_RUNTIME_LOCK:
                        if CAMERA_RUNTIME.get("session_id") == session_id:
                            CAMERA_RUNTIME["error"] = f"camera read failed from {opened_source}: {last_error}"
                    break
                if read_failures % 10 == 0:
                    with CAMERA_RUNTIME_LOCK:
                        if CAMERA_RUNTIME.get("session_id") == session_id:
                            CAMERA_RUNTIME["error"] = f"camera waiting frame from {opened_source}: {last_error}"
                time.sleep(0.05)
                continue

            got_frame = True
            read_failures = 0
            now = time.time()
            with CAMERA_RUNTIME_LOCK:
                if CAMERA_RUNTIME.get("session_id") != session_id:
                    break
                seq = int(CAMERA_RUNTIME.get("latest_frame_seq") or 0) + 1
                packet = _packet_from_frame(frame, seq, now, str(opened_source or "camera"))
                CAMERA_RUNTIME["last_frame_raw"] = frame
                CAMERA_RUNTIME["last_frame_packet"] = packet
                CAMERA_RUNTIME["last_frame_format"] = packet.pixel_format
                CAMERA_RUNTIME["last_frame_width"] = packet.width
                CAMERA_RUNTIME["last_frame_height"] = packet.height
                CAMERA_RUNTIME["last_frame_buffer_size"] = packet.buffer_size
                CAMERA_RUNTIME["last_frame_stride_w"] = packet.stride_w
                CAMERA_RUNTIME["last_frame_stride_h"] = packet.stride_h
                CAMERA_RUNTIME["last_frame_stride_inferred"] = packet.stride_inferred
                CAMERA_RUNTIME["latest_frame_seq"] = seq
                CAMERA_RUNTIME["latest_frame_mtime"] = now

            if mode == "auto" and now >= next_auto_time:
                try:
                    processed = get_preprocess_engine().process_for_save(packet)
                    _enforce_required_rga("save", capture_backend, processed, require_rga)
                    decision = get_selector().decision(processed, _selector_context())
                    if decision.get("keep"):
                        with CAMERA_RUNTIME_LOCK:
                            frame_index = int(CAMERA_RUNTIME.get("capture_count") or 0) + 1
                        _, save_msg = _save_processed_frame(processed, session_id, frame_index, selector_decision=decision)
                        if save_msg:
                            with CAMERA_RUNTIME_LOCK:
                                if CAMERA_RUNTIME.get("session_id") == session_id:
                                    CAMERA_RUNTIME["error"] = save_msg
                    else:
                        with CAMERA_RUNTIME_LOCK:
                            if CAMERA_RUNTIME.get("session_id") == session_id:
                                CAMERA_RUNTIME["dropped_count"] = int(CAMERA_RUNTIME.get("dropped_count") or 0) + 1
                                CAMERA_RUNTIME["last_selector_decision"] = copy.deepcopy(decision)
                except Exception as exc:
                    with CAMERA_RUNTIME_LOCK:
                        if CAMERA_RUNTIME.get("session_id") == session_id:
                            CAMERA_RUNTIME["error"] = f"auto keyframe/save failed: {exc}"
                next_auto_time = now + config.CAMERA_AUTO_INTERVAL_SEC
            time.sleep(0.001)

    except Exception as exc:
        with CAMERA_RUNTIME_LOCK:
            if CAMERA_RUNTIME.get("session_id") == session_id:
                CAMERA_RUNTIME["error"] = f"camera capture error: {exc}"
    finally:
        try:
            stop_event.set()
        except Exception:
            pass
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        with CAMERA_RUNTIME_LOCK:
            if CAMERA_RUNTIME.get("session_id") == session_id:
                CAMERA_RUNTIME["active"] = False
                CAMERA_RUNTIME["thread"] = None
                CAMERA_RUNTIME["stop_event"] = None
                CAMERA_RUNTIME["last_frame_raw"] = None
                CAMERA_RUNTIME["last_frame_packet"] = None
                CAMERA_RUNTIME["last_frame_format"] = ""
                CAMERA_RUNTIME["last_frame_width"] = 0
                CAMERA_RUNTIME["last_frame_height"] = 0
                CAMERA_RUNTIME["last_frame_buffer_size"] = 0
                CAMERA_RUNTIME["last_frame_stride_w"] = 0
                CAMERA_RUNTIME["last_frame_stride_h"] = 0
                CAMERA_RUNTIME["last_frame_stride_inferred"] = False
                CAMERA_RUNTIME["last_frame_jpeg"] = b""
                CAMERA_RUNTIME["latest_frame_seq"] = 0
                CAMERA_RUNTIME["latest_frame_mtime"] = 0.0
                CAMERA_RUNTIME["preview_frame_seq"] = 0
                CAMERA_RUNTIME["stopped_at"] = time.time()


def _camera_preview_encode_loop(session_id: str, stop_event: threading.Event) -> None:
    try:
        preview_interval_sec = 1.0 / max(1, config.CAMERA_PREVIEW_FPS)
        last_encoded_seq = 0
        next_encode_at = 0.0
        while not stop_event.is_set():
            now = time.time()
            if now < next_encode_at:
                time.sleep(min(0.01, next_encode_at - now))
                continue
            with CAMERA_RUNTIME_LOCK:
                if CAMERA_RUNTIME.get("session_id") != session_id:
                    break
                active = bool(CAMERA_RUNTIME.get("active"))
                packet = CAMERA_RUNTIME.get("last_frame_packet")
                frame_seq = int(CAMERA_RUNTIME.get("latest_frame_seq") or 0)
            if packet is None or frame_seq <= last_encoded_seq:
                if not active and packet is None:
                    break
                time.sleep(0.005)
                continue
            try:
                processed = get_preprocess_engine().process_for_preview(packet)
                with CAMERA_RUNTIME_LOCK:
                    capture_backend = CAMERA_RUNTIME.get("capture_backend") or config.CAMERA_CAPTURE_BACKEND
                    require_rga = bool(CAMERA_RUNTIME.get("require_rga"))
                _enforce_required_rga("preview", capture_backend, processed, require_rga)
            except Exception as exc:
                with CAMERA_RUNTIME_LOCK:
                    if CAMERA_RUNTIME.get("session_id") == session_id:
                        CAMERA_RUNTIME["error"] = f"camera preview encode failed: {exc}"
                time.sleep(0.05)
                continue
            if not processed.preview_jpeg:
                time.sleep(0.01)
                continue
            stamp = time.time()
            with CAMERA_RUNTIME_LOCK:
                if CAMERA_RUNTIME.get("session_id") != session_id:
                    break
                CAMERA_RUNTIME["last_frame_jpeg"] = processed.preview_jpeg
                CAMERA_RUNTIME["last_frame_mtime"] = stamp
                CAMERA_RUNTIME["preview_frame_seq"] = frame_seq
            last_encoded_seq = frame_seq
            next_encode_at = stamp + preview_interval_sec
    except Exception as exc:
        with CAMERA_RUNTIME_LOCK:
            if CAMERA_RUNTIME.get("session_id") == session_id:
                CAMERA_RUNTIME["error"] = f"camera preview thread error: {exc}"
    finally:
        with CAMERA_RUNTIME_LOCK:
            if CAMERA_RUNTIME.get("session_id") == session_id:
                CAMERA_RUNTIME["preview_thread"] = None


def start_camera_session(payload: dict) -> dict:
    capture_mode = (str(payload.get("mode", "manual")).strip().lower() if isinstance(payload, dict) else "manual")
    if capture_mode not in ("manual", "auto"):
        return {"ok": False, "msg": "camera mode must be manual or auto"}
    capture_backend = config.CAMERA_CAPTURE_BACKEND
    if isinstance(payload, dict) and payload.get("capture_backend") is not None:
        capture_backend = config.normalize_camera_capture_backend(payload.get("capture_backend"))
    require_rga = bool(payload.get("require_rga")) if isinstance(payload, dict) else False
    backend = get_camera_backend_status()
    if not backend.get("enabled"):
        return {"ok": False, "msg": backend.get("msg") or "camera backend unavailable"}
    preprocess_status = backend.get("preprocess") or {}
    if require_rga and preprocess_status.get("requested") != "rga":
        return {"ok": False, "msg": "require_rga needs accel.preprocess=rga"}

    with CAMERA_RUNTIME_LOCK:
        if CAMERA_RUNTIME.get("active"):
            return {
                "ok": False,
                "msg": "camera session already running",
                "session_id": CAMERA_RUNTIME.get("session_id") or "",
                "mode": CAMERA_RUNTIME.get("mode") or "",
            }
        session_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        stop_event = threading.Event()
        thread = threading.Thread(
            target=_camera_capture_loop,
            args=(session_id, capture_mode, stop_event, capture_backend, require_rga),
            daemon=True,
        )
        preview_thread = threading.Thread(target=_camera_preview_encode_loop, args=(session_id, stop_event), daemon=True)
        CAMERA_RUNTIME.update({
            "active": True,
            "mode": capture_mode,
            "session_id": session_id,
            "started_at": time.time(),
            "stopped_at": 0.0,
            "capture_files": [],
            "capture_count": 0,
            "last_capture_name": "",
            "last_capture_mtime": 0,
            "last_frame_jpeg": b"",
            "last_frame_raw": None,
            "last_frame_packet": None,
            "last_frame_mtime": 0.0,
            "latest_frame_seq": 0,
            "latest_frame_mtime": 0.0,
            "preview_frame_seq": 0,
            "error": "",
            "stop_event": stop_event,
            "thread": thread,
            "preview_thread": preview_thread,
            "last_result": {},
            "open_source": "",
            "open_attempts": [],
            "capture_backend": capture_backend,
            "require_rga": require_rga,
            "last_frame_format": "",
            "last_frame_width": 0,
            "last_frame_height": 0,
            "last_frame_buffer_size": 0,
            "last_frame_stride_w": 0,
            "last_frame_stride_h": 0,
            "last_frame_stride_inferred": False,
            "last_preview_preprocess": {},
            "last_save_preprocess": {},
            "last_keep_ts": 0.0,
            "last_keep_image": None,
            "last_selector_decision": {},
            "dropped_count": 0,
        })
        thread.start()
        preview_thread.start()

    wait_deadline = time.time() + 0.35
    while time.time() < wait_deadline:
        snap = _camera_runtime_snapshot()
        if snap.get("session_id") != session_id:
            break
        if snap.get("last_frame_ready"):
            break
        if not snap.get("active") and snap.get("error"):
            break
        time.sleep(0.06)

    snap = _camera_runtime_snapshot()
    if snap.get("session_id") != session_id:
        return {"ok": False, "msg": "camera session interrupted"}
    if not snap.get("active") and snap.get("error"):
        return {"ok": False, "msg": snap.get("error") or "camera start failed"}
    return {
        "ok": True,
        "msg": "camera starting" if not snap.get("last_frame_ready") else "camera started",
        "session_id": session_id,
        "mode": capture_mode,
        "backend": config.CAMERA_BACKEND,
        "capture_backend": capture_backend,
        "require_rga": require_rga,
        "source": config.CAMERA_SOURCE,
        "source_text": config.camera_source_text(),
        "device": _camera_primary_device(),
        "device_candidates": backend.get("device_candidates") or [],
        "pixel_format": config.CAMERA_PIXEL_FORMAT,
        "rotation": config.CAMERA_ROTATION,
        "frame_width": config.camera_effective_width(),
        "frame_height": config.camera_effective_height(),
        "fps": config.camera_effective_fps(),
        "preview_max_dim": config.CAMERA_PREVIEW_MAX_DIM,
        "preview_jpeg_quality": config.CAMERA_PREVIEW_JPEG_QUALITY,
        "preview_fps": config.CAMERA_PREVIEW_FPS,
        "open_source": snap.get("open_source", ""),
        "last_frame_ready": bool(snap.get("last_frame_ready")),
        "auto_interval_sec": config.CAMERA_AUTO_INTERVAL_SEC,
        "input_dir": config.STITCH_INPUT_DIR,
        "capture_count": snap.get("capture_count", 0),
        "preprocess": get_preprocess_status(),
        "selector": get_selector_status(),
    }


def capture_camera_snapshot() -> dict:
    with CAMERA_RUNTIME_LOCK:
        if not CAMERA_RUNTIME.get("active"):
            return {"ok": False, "msg": "camera session is not running"}
        if CAMERA_RUNTIME.get("mode") != "manual":
            return {"ok": False, "msg": "manual capture is only available in manual mode"}
        packet = CAMERA_RUNTIME.get("last_frame_packet")
        if packet is None:
            return {"ok": False, "msg": "camera frame is not ready"}
        capture_backend = CAMERA_RUNTIME.get("capture_backend") or config.CAMERA_CAPTURE_BACKEND
        require_rga = bool(CAMERA_RUNTIME.get("require_rga"))
        packet_copy = _copy_frame_packet(packet, time.time())
        session_id = CAMERA_RUNTIME.get("session_id") or ""
        next_index = int(CAMERA_RUNTIME.get("capture_count") or 0) + 1
    try:
        processed = get_preprocess_engine().process_for_save(packet_copy)
        _enforce_required_rga("save", capture_backend, processed, require_rga)
    except Exception as exc:
        return {"ok": False, "msg": f"preprocess failed: {exc}"}
    item, save_msg = _save_processed_frame(processed, session_id, next_index, selector_decision={"keep": True, "reason": "manual"})
    if save_msg:
        return {"ok": False, "msg": save_msg}
    if not item:
        return {"ok": False, "msg": "failed to save camera frame"}
    return {
        "ok": True,
        "msg": "captured",
        "capture_count": int(_camera_runtime_snapshot().get("capture_count", 0)),
        "file": item,
        "capture_backend": capture_backend,
        "preprocess": get_preprocess_status(),
    }


def stop_camera_session(payload: dict) -> dict:
    auto_crop = bool(payload.get("auto_crop")) if isinstance(payload, dict) else False
    with CAMERA_RUNTIME_LOCK:
        session_id = CAMERA_RUNTIME.get("session_id") or ""
        capture_mode = CAMERA_RUNTIME.get("mode") or ""
        stop_event = CAMERA_RUNTIME.get("stop_event")
        thread = CAMERA_RUNTIME.get("thread")
        preview_thread = CAMERA_RUNTIME.get("preview_thread")
        was_active = bool(CAMERA_RUNTIME.get("active"))
    if not session_id:
        return {"ok": False, "msg": "camera session has not started"}
    if stop_event is not None:
        stop_event.set()
    if thread is not None:
        try:
            thread.join(timeout=4.0)
        except Exception:
            pass
    if preview_thread is not None:
        try:
            preview_thread.join(timeout=2.0)
        except Exception:
            pass
    with CAMERA_RUNTIME_LOCK:
        if CAMERA_RUNTIME.get("session_id") == session_id:
            CAMERA_RUNTIME["active"] = False
            CAMERA_RUNTIME["stop_event"] = None
            CAMERA_RUNTIME["thread"] = None
            CAMERA_RUNTIME["preview_thread"] = None
            CAMERA_RUNTIME["last_frame_raw"] = None
            CAMERA_RUNTIME["last_frame_packet"] = None
            CAMERA_RUNTIME["last_frame_format"] = ""
            CAMERA_RUNTIME["last_frame_width"] = 0
            CAMERA_RUNTIME["last_frame_height"] = 0
            CAMERA_RUNTIME["last_frame_buffer_size"] = 0
            CAMERA_RUNTIME["last_frame_stride_w"] = 0
            CAMERA_RUNTIME["last_frame_stride_h"] = 0
            CAMERA_RUNTIME["last_frame_stride_inferred"] = False
            CAMERA_RUNTIME["last_frame_jpeg"] = b""
            CAMERA_RUNTIME["last_frame_mtime"] = 0.0
            CAMERA_RUNTIME["latest_frame_seq"] = 0
            CAMERA_RUNTIME["latest_frame_mtime"] = 0.0
            CAMERA_RUNTIME["preview_frame_seq"] = 0
            CAMERA_RUNTIME["stopped_at"] = time.time()
            capture_files = list(CAMERA_RUNTIME.get("capture_files") or [])
            capture_count = len(capture_files)
            session_error = CAMERA_RUNTIME.get("error") or ""
            dropped_count = int(CAMERA_RUNTIME.get("dropped_count") or 0)
        else:
            capture_files = list(CAMERA_RUNTIME.get("capture_files") or [])
            capture_count = len(capture_files)
            session_error = CAMERA_RUNTIME.get("error") or ""
            dropped_count = int(CAMERA_RUNTIME.get("dropped_count") or 0)

    if capture_count < 2:
        result = {
            "ok": False,
            "msg": "need at least two captured images before stitching",
            "mode": capture_mode,
            "was_active": was_active,
            "capture_count": capture_count,
            "capture_files": capture_files,
            "session_id": session_id,
            "error": session_error,
            "dropped_count": dropped_count,
        }
        with CAMERA_RUNTIME_LOCK:
            if CAMERA_RUNTIME.get("session_id") == session_id:
                CAMERA_RUNTIME["last_result"] = copy.deepcopy(result)
        return result

    stitch_result = run_image_stitch({"server_files": capture_files, "auto_crop": auto_crop, "source": "camera"})
    result = {
        "ok": stitch_result.get("ok", False),
        "msg": stitch_result.get("msg") or ("stitched" if stitch_result.get("ok") else "stitch failed"),
        "mode": capture_mode,
        "was_active": was_active,
        "capture_count": capture_count,
        "capture_files": capture_files,
        "session_id": session_id,
        "auto_crop": auto_crop,
        "error": session_error,
        "dropped_count": dropped_count,
    }
    for key in ("result_name", "result_url", "image_count", "engine", "actual_engine", "log_id", "stitch_log"):
        if stitch_result.get(key) is not None:
            result[key] = stitch_result.get(key)
    with CAMERA_RUNTIME_LOCK:
        if CAMERA_RUNTIME.get("session_id") == session_id:
            CAMERA_RUNTIME["last_result"] = copy.deepcopy(result)
    return result


def get_camera_stream_frame(session_id: str = ""):
    with CAMERA_RUNTIME_LOCK:
        current_session = CAMERA_RUNTIME.get("session_id") or ""
        active = bool(CAMERA_RUNTIME.get("active"))
        frame = CAMERA_RUNTIME.get("last_frame_jpeg") or b""
        mtime = float(CAMERA_RUNTIME.get("last_frame_mtime") or 0.0)
        seq = int(CAMERA_RUNTIME.get("preview_frame_seq") or CAMERA_RUNTIME.get("latest_frame_seq") or 0)
    if session_id and current_session != session_id:
        return b"", False, current_session, 0.0, 0
    return frame, active, current_session, mtime, seq


def get_camera_frame_jpeg(session_id: str = ""):
    return get_camera_stream_frame(session_id=session_id)
