#!/usr/bin/env python3
"""Runtime configuration for the RK3588 stitching GUI backend.

The module keeps the old flat constants available to services while adding the
new accelerator selection block.  Defaults are deliberately conservative: CPU
paths are always valid and every accelerator can fall back without crashing.
"""
from __future__ import annotations

import copy
import json
import os
import re
from typing import Any, Dict

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEVICE_BASE_DIR = "/userdata/myui"
BASE_DIR = os.environ.get("MYUI_BASE_DIR") or (
    DEVICE_BASE_DIR if os.path.isdir(DEVICE_BASE_DIR) else SCRIPT_DIR
)
CONFIG_PATH = os.environ.get("MYUI_CONFIG") or os.path.join(BASE_DIR, "config.json")

FONT_SIZE_PRESETS = {
    "small": 0.92,
    "medium": 1.00,
    "large": 1.10,
    "xlarge": 1.22,
}
FONT_SIZE_LABELS = {
    "small": "小",
    "medium": "中",
    "large": "大",
    "xlarge": "特大",
}
FONT_SIZE_ALIASES = {
    "small": "small",
    "medium": "medium",
    "large": "large",
    "xlarge": "xlarge",
    "s": "small",
    "m": "medium",
    "l": "large",
    "xl": "xlarge",
    "xxl": "xlarge",
    "小": "small",
    "中": "medium",
    "大": "large",
    "特大": "xlarge",
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "system": {
        "port": 18080,
        "log_file": "./backend.log",
        "switch_script": "./switch_to_systemui.sh",
    },
    "ui": {
        "font_size": "medium",
    },
    "accel": {
        "preprocess": "rga",
        "geometry": "cpu",
        "selector": "off",
    },
    "selector": {
        "cpu_basic": {
            "min_interval_sec": 0.5,
            "blur_threshold": 60.0,
            "diff_threshold": 3.0,
            "diff_resize_width": 320,
        }
    },
    "stitch": {
        "engine": "builtin",
        "script_path": "./stitch_demo.py",
        "python_bin": "python3",
        "script_timeout_sec": 180,
        "work_dir": "./_stitch_work",
        "input_dir": "./stitch_input",
        "output_dir": "./stitch_output",
        "input_url_prefix": "/stitch_input/",
        "output_url_prefix": "/stitch_output/",
        "max_image_bytes": 15728640,
        "max_canvas_pixels": 8000000,
        "multiband_max_canvas_pixels": 3000000,
        "postprocess_denoise_max_pixels": 1500000,
        "viewer": {
            "haov": 360,
            "vaov": 60,
            "v_offset": 0,
            "initial_yaw": 0,
            "initial_pitch": 0,
            "initial_hfov": 100,
            "min_pitch": -25,
            "max_pitch": 25,
            "min_hfov": 60,
            "max_hfov": 110,
        },
        "camera": {
            "backend": "auto",
            "capture_backend": "auto_raw",
            "source": "/dev/video-camera0",
            "pixel_format": "NV12",
            "rotation": "ccw90",
            "frame_width": 1920,
            "frame_height": 1080,
            "fps": 30,
            "v4l2_buffer_count": 4,
            "preview_max_dim": 960,
            "preview_jpeg_quality": 70,
            "preview_fps": 30,
            "auto_interval_sec": 0.5,
            "jpeg_quality": 88,
        },
    },
}

ALLOWED_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")


def deep_merge(base: Dict[str, Any], override: Dict[str, Any] | None) -> Dict[str, Any]:
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def write_default_config_if_missing(path: str) -> None:
    if os.path.exists(path):
        return
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception:
        # Backend must still be importable if the target filesystem is read-only.
        pass


def load_config(path: str) -> Dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    write_default_config_if_missing(path)
    if not os.path.isfile(path):
        return config
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            deep_merge(config, loaded)
    except Exception:
        pass
    return config


def resolve_path(raw_path: Any, fallback: str) -> str:
    value = (str(raw_path).strip() if raw_path is not None else "").strip()
    if not value:
        value = fallback
    if os.path.isabs(value):
        return os.path.normpath(value)
    return os.path.normpath(os.path.join(BASE_DIR, value))


def normalize_url_prefix(raw_prefix: Any, fallback: str) -> str:
    value = (str(raw_prefix).strip() if raw_prefix is not None else "").strip()
    if not value:
        value = fallback
    if not value.startswith("/"):
        value = "/" + value
    parts = [part for part in value.split("/") if part]
    if not parts:
        return "/"
    return "/" + "/".join(parts) + "/"


def normalize_font_size(raw_value: Any) -> str:
    value = (str(raw_value).strip().lower() if raw_value is not None else "").strip()
    mapped = FONT_SIZE_ALIASES.get(value, value)
    if mapped not in FONT_SIZE_PRESETS:
        return "medium"
    return mapped


def normalize_camera_backend(raw_value: Any) -> str:
    value = (str(raw_value).strip().lower() if raw_value is not None else "").strip()
    aliases = {
        "": "auto",
        "default": "auto",
        "opencv-gst": "gstreamer",
        "gst": "gstreamer",
        "opencv": "opencv",
        "cv2": "opencv",
        "v4l2": "v4l2ctl",
        "v4l2-ctl": "v4l2ctl",
        "v4l2ctl": "v4l2ctl",
    }
    value = aliases.get(value, value)
    if value not in ("auto", "gstreamer", "opencv", "v4l2ctl"):
        return "auto"
    return value


def normalize_camera_capture_backend(raw_value: Any) -> str:
    value = (str(raw_value).strip().lower() if raw_value is not None else "").strip()
    aliases = {
        "": "legacy_bgr",
        "auto_raw": "auto_raw",
        "raw_auto": "auto_raw",
        "raw-auto": "auto_raw",
        "nv12_auto": "auto_raw",
        "nv12-auto": "auto_raw",
        "default": "legacy_bgr",
        "legacy": "legacy_bgr",
        "bgr": "legacy_bgr",
        "opencv": "legacy_bgr",
        "gst": "legacy_bgr",
        "gstreamer": "legacy_bgr",
        "raw": "gst_nv12_raw",
        "nv12": "gst_nv12_raw",
        "gst_raw": "gst_nv12_raw",
        "gst-nv12-raw": "gst_nv12_raw",
        "v4l2_raw": "v4l2ctl_nv12_raw",
        "v4l2-nv12-raw": "v4l2ctl_nv12_raw",
        "v4l2ctl_raw": "v4l2ctl_nv12_raw",
        "v4l2ctl-nv12-raw": "v4l2ctl_nv12_raw",
    }
    value = aliases.get(value, value)
    if value not in ("auto_raw", "legacy_bgr", "gst_nv12_raw", "v4l2ctl_nv12_raw"):
        return "legacy_bgr"
    return value


def normalize_camera_rotation(raw_value: Any) -> str:
    value = (str(raw_value).strip().lower() if raw_value is not None else "").strip()
    aliases = {
        "": "none",
        "0": "none",
        "none": "none",
        "no": "none",
        "off": "none",
        "normal": "none",
        "90ccw": "ccw90",
        "ccw90": "ccw90",
        "counterclockwise90": "ccw90",
        "counter_clockwise90": "ccw90",
        "anticlockwise90": "ccw90",
        "left": "ccw90",
        "90cw": "cw90",
        "cw90": "cw90",
        "clockwise90": "cw90",
        "right": "cw90",
        "180": "180",
        "rotate180": "180",
        "flip": "180",
    }
    value = aliases.get(value, value)
    if value not in ("none", "ccw90", "cw90", "180"):
        return "none"
    return value


def parse_camera_source(raw_value: Any) -> int | str:
    if isinstance(raw_value, int):
        return raw_value
    value = (str(raw_value).strip() if raw_value is not None else "").strip()
    if not value:
        return 0
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except Exception:
            return 0
    return value


def safe_int(raw: Any, default_value: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        value = int(raw)
    except Exception:
        value = default_value
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def safe_float(raw: Any, default_value: float, min_value: float | None = None, max_value: float | None = None) -> float:
    try:
        value = float(raw)
    except Exception:
        value = default_value
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def normalize_choice(raw_value: Any, default_value: str, allowed: tuple[str, ...], aliases: Dict[str, str] | None = None) -> str:
    value = (str(raw_value).strip().lower() if raw_value is not None else "").strip()
    value = (aliases or {}).get(value, value)
    if not value:
        value = default_value
    if value not in allowed:
        return default_value
    return value


APP_CONFIG = load_config(CONFIG_PATH)
SYSTEM_CONFIG = APP_CONFIG.get("system", {}) if isinstance(APP_CONFIG.get("system"), dict) else {}
UI_CONFIG = APP_CONFIG.get("ui", {}) if isinstance(APP_CONFIG.get("ui"), dict) else {}
ACCEL_CONFIG = APP_CONFIG.get("accel", {}) if isinstance(APP_CONFIG.get("accel"), dict) else {}
SELECTOR_CONFIG = APP_CONFIG.get("selector", {}) if isinstance(APP_CONFIG.get("selector"), dict) else {}
STITCH_CONFIG = APP_CONFIG.get("stitch", {}) if isinstance(APP_CONFIG.get("stitch"), dict) else {}
CAMERA_CONFIG = STITCH_CONFIG.get("camera", {}) if isinstance(STITCH_CONFIG.get("camera"), dict) else {}
PANORAMA_VIEWER_CONFIG = STITCH_CONFIG.get("viewer", {}) if isinstance(STITCH_CONFIG.get("viewer"), dict) else {}

PORT = int(os.environ.get("MYUI_PORT", str(SYSTEM_CONFIG.get("port", 18080))))
LOG = resolve_path(SYSTEM_CONFIG.get("log_file"), "./backend.log")
SWITCH_SCRIPT = resolve_path(SYSTEM_CONFIG.get("switch_script"), "./switch_to_systemui.sh")

STITCH_WORK_DIR = resolve_path(STITCH_CONFIG.get("work_dir"), "./_stitch_work")
STITCH_OUTPUT_DIR = resolve_path(STITCH_CONFIG.get("output_dir"), "./stitch_output")
STITCH_INPUT_DIR = resolve_path(STITCH_CONFIG.get("input_dir"), "./stitch_input")
STITCH_INPUT_URL_PREFIX = normalize_url_prefix(STITCH_CONFIG.get("input_url_prefix"), "/stitch_input/")
STITCH_OUTPUT_URL_PREFIX = normalize_url_prefix(STITCH_CONFIG.get("output_url_prefix"), "/stitch_output/")
STITCH_ENGINE = normalize_choice(
    STITCH_CONFIG.get("engine", "builtin"),
    "builtin",
    ("builtin", "script", "opencv", "sequential", "scans"),
    {"cv2": "opencv", "opencvstitch": "opencv", "scan": "scans", "opencvscans": "scans"},
)
if STITCH_ENGINE == "opencv":
    STITCH_ENGINE = "builtin"
STITCH_SCRIPT = resolve_path(STITCH_CONFIG.get("script_path"), "./stitch_demo.py")
STITCH_SCRIPT_PYTHON = str(STITCH_CONFIG.get("python_bin", "python3")).strip() or "python3"
STITCH_SCRIPT_TIMEOUT_SEC = safe_int(STITCH_CONFIG.get("script_timeout_sec", 180), 180, min_value=10)
MAX_STITCH_IMAGE_BYTES = safe_int(
    STITCH_CONFIG.get("max_image_bytes", 15 * 1024 * 1024),
    15 * 1024 * 1024,
    min_value=1024,
)
MAX_STITCH_CANVAS_PIXELS = safe_int(
    STITCH_CONFIG.get("max_canvas_pixels", 8_000_000),
    8_000_000,
    min_value=1_000_000,
    max_value=32_000_000,
)
MULTIBAND_MAX_STITCH_CANVAS_PIXELS = min(
    MAX_STITCH_CANVAS_PIXELS,
    safe_int(
        STITCH_CONFIG.get("multiband_max_canvas_pixels", 3_000_000),
        3_000_000,
        min_value=250_000,
        max_value=MAX_STITCH_CANVAS_PIXELS,
    ),
)
MAX_STITCH_DENOISE_PIXELS = safe_int(
    STITCH_CONFIG.get("postprocess_denoise_max_pixels", 1_500_000),
    1_500_000,
    min_value=0,
    max_value=16_000_000,
)

PANORAMA_HAOV = safe_float(PANORAMA_VIEWER_CONFIG.get("haov", 360), 360, min_value=1.0, max_value=360.0)
PANORAMA_VAOV = safe_float(PANORAMA_VIEWER_CONFIG.get("vaov", 60), 60, min_value=1.0, max_value=180.0)
PANORAMA_V_OFFSET = safe_float(PANORAMA_VIEWER_CONFIG.get("v_offset", 0), 0, min_value=-90.0, max_value=90.0)
PANORAMA_INITIAL_YAW = safe_float(PANORAMA_VIEWER_CONFIG.get("initial_yaw", 0), 0, min_value=-360.0, max_value=360.0)
PANORAMA_INITIAL_PITCH = safe_float(PANORAMA_VIEWER_CONFIG.get("initial_pitch", 0), 0, min_value=-90.0, max_value=90.0)
PANORAMA_INITIAL_HFOV = safe_float(PANORAMA_VIEWER_CONFIG.get("initial_hfov", 100), 100, min_value=1.0, max_value=170.0)
PANORAMA_MIN_PITCH = safe_float(PANORAMA_VIEWER_CONFIG.get("min_pitch", -25), -25, min_value=-90.0, max_value=90.0)
PANORAMA_MAX_PITCH = safe_float(PANORAMA_VIEWER_CONFIG.get("max_pitch", 25), 25, min_value=-90.0, max_value=90.0)
if PANORAMA_MIN_PITCH > PANORAMA_MAX_PITCH:
    PANORAMA_MIN_PITCH, PANORAMA_MAX_PITCH = PANORAMA_MAX_PITCH, PANORAMA_MIN_PITCH
PANORAMA_INITIAL_PITCH = min(max(PANORAMA_INITIAL_PITCH, PANORAMA_MIN_PITCH), PANORAMA_MAX_PITCH)
PANORAMA_MIN_HFOV = safe_float(PANORAMA_VIEWER_CONFIG.get("min_hfov", 60), 60, min_value=1.0, max_value=170.0)
PANORAMA_MAX_HFOV = safe_float(PANORAMA_VIEWER_CONFIG.get("max_hfov", 110), 110, min_value=1.0, max_value=170.0)
if PANORAMA_MIN_HFOV > PANORAMA_MAX_HFOV:
    PANORAMA_MIN_HFOV, PANORAMA_MAX_HFOV = PANORAMA_MAX_HFOV, PANORAMA_MIN_HFOV
PANORAMA_INITIAL_HFOV = min(max(PANORAMA_INITIAL_HFOV, PANORAMA_MIN_HFOV), PANORAMA_MAX_HFOV)

ACCEL_PREPROCESS = normalize_choice(
    ACCEL_CONFIG.get("preprocess", "cpu"),
    "cpu",
    ("cpu", "rga"),
)
ACCEL_GEOMETRY = normalize_choice(
    ACCEL_CONFIG.get("geometry", "cpu"),
    "cpu",
    ("cpu", "opencl"),
)
ACCEL_SELECTOR = normalize_choice(
    ACCEL_CONFIG.get("selector", "off"),
    "off",
    ("off", "cpu_basic", "rknn"),
    {"cpu": "cpu_basic", "basic": "cpu_basic", "rknn_selector": "rknn"},
)

CAMERA_BACKEND = normalize_camera_backend(CAMERA_CONFIG.get("backend", "auto"))
CAMERA_CAPTURE_BACKEND = normalize_camera_capture_backend(CAMERA_CONFIG.get("capture_backend", "auto_raw"))
CAMERA_SOURCE = parse_camera_source(CAMERA_CONFIG.get("source", "/dev/video-camera0"))
CAMERA_PIXEL_FORMAT = (str(CAMERA_CONFIG.get("pixel_format", "NV12")).strip().upper() or "NV12")
if CAMERA_PIXEL_FORMAT not in ("NV12", "NV21"):
    CAMERA_PIXEL_FORMAT = "NV12"
CAMERA_ROTATION = normalize_camera_rotation(CAMERA_CONFIG.get("rotation", "ccw90"))
CAMERA_FRAME_WIDTH = safe_int(CAMERA_CONFIG.get("frame_width", 1920), 1920, min_value=0)
CAMERA_FRAME_HEIGHT = safe_int(CAMERA_CONFIG.get("frame_height", 1080), 1080, min_value=0)
CAMERA_TARGET_FPS = safe_int(CAMERA_CONFIG.get("fps", 30), 30, min_value=0)
CAMERA_V4L2_BUFFER_COUNT = safe_int(CAMERA_CONFIG.get("v4l2_buffer_count", 4), 4, min_value=1, max_value=16)
CAMERA_PREVIEW_MAX_DIM = safe_int(CAMERA_CONFIG.get("preview_max_dim", 960), 960, min_value=0, max_value=4096)
CAMERA_PREVIEW_JPEG_QUALITY = safe_int(CAMERA_CONFIG.get("preview_jpeg_quality", 70), 70, min_value=35, max_value=95)
CAMERA_PREVIEW_FPS = safe_int(CAMERA_CONFIG.get("preview_fps", 15), 15, min_value=1, max_value=30)
CAMERA_AUTO_INTERVAL_SEC = safe_float(CAMERA_CONFIG.get("auto_interval_sec", 0.5), 0.5, min_value=0.1, max_value=10.0)
CAMERA_JPEG_QUALITY = safe_int(CAMERA_CONFIG.get("jpeg_quality", 88), 88, min_value=40, max_value=100)

CPU_SELECTOR_CONFIG = SELECTOR_CONFIG.get("cpu_basic", {}) if isinstance(SELECTOR_CONFIG.get("cpu_basic"), dict) else {}
CPU_SELECTOR_MIN_INTERVAL_SEC = safe_float(
    CPU_SELECTOR_CONFIG.get("min_interval_sec", CAMERA_AUTO_INTERVAL_SEC),
    CAMERA_AUTO_INTERVAL_SEC,
    min_value=0.0,
    max_value=60.0,
)
CPU_SELECTOR_BLUR_THRESHOLD = safe_float(
    CPU_SELECTOR_CONFIG.get("blur_threshold", 60.0),
    60.0,
    min_value=0.0,
    max_value=1000000.0,
)
CPU_SELECTOR_DIFF_THRESHOLD = safe_float(
    CPU_SELECTOR_CONFIG.get("diff_threshold", 3.0),
    3.0,
    min_value=0.0,
    max_value=255.0,
)
CPU_SELECTOR_DIFF_RESIZE_WIDTH = safe_int(
    CPU_SELECTOR_CONFIG.get("diff_resize_width", 320),
    320,
    min_value=32,
    max_value=2048,
)

UI_FONT_SIZE = normalize_font_size(UI_CONFIG.get("font_size", "medium"))
UI_FONT_ZOOM = FONT_SIZE_PRESETS[UI_FONT_SIZE]

for path in (STITCH_WORK_DIR, STITCH_OUTPUT_DIR, STITCH_INPUT_DIR):
    os.makedirs(path, exist_ok=True)
try:
    log_dir = os.path.dirname(LOG)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
except Exception:
    pass

# Preserve old backend behavior: relative static paths resolve from the deploy dir.
os.chdir(BASE_DIR)


def camera_source_text() -> str:
    return str(CAMERA_SOURCE)


def camera_device_path() -> str:
    source = CAMERA_SOURCE
    if isinstance(source, int):
        return f"/dev/video{source}" if source >= 0 else ""
    source_str = (str(source).strip() if source is not None else "").strip()
    if not source_str:
        return "/dev/video-camera0"
    if source_str.startswith("/dev/video"):
        return source_str
    if re.fullmatch(r"-?\d+", source_str):
        try:
            index = int(source_str)
            return f"/dev/video{index}" if index >= 0 else ""
        except Exception:
            return ""
    return ""


def camera_effective_width() -> int:
    return CAMERA_FRAME_WIDTH if CAMERA_FRAME_WIDTH > 0 else 1920


def camera_effective_height() -> int:
    return CAMERA_FRAME_HEIGHT if CAMERA_FRAME_HEIGHT > 0 else 1080


def camera_effective_fps() -> int:
    return CAMERA_TARGET_FPS if CAMERA_TARGET_FPS > 0 else 30
