#!/usr/bin/env python3
"""System/config routes."""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any

from app import config
from app.services.geometry_service import get_geometry_status
from app.services.keyframe_service import get_selector_status
from app.services.preprocess_service import get_preprocess_status
from app.utils.log import log


def run_cmd(cmd: str) -> str:
    try:
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
        return out.decode("utf-8", errors="ignore").strip()
    except subprocess.CalledProcessError as exc:
        return exc.output.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _iface_priority(name: str):
    if name.startswith("wlan"):
        return (0, name)
    if name.startswith("eth") or name.startswith("en"):
        return (1, name)
    return (2, name)


def _append_ip(items: list, seen: set, iface: str, ip: str) -> None:
    iface = (iface or "").split("@", 1)[0].strip()
    ip = (ip or "").strip()
    if not iface or not ip:
        return
    key = (iface, ip)
    if key in seen:
        return
    items.append({"iface": iface, "ip": ip})
    seen.add(key)


def _parse_ip_output(raw: str) -> list:
    items = []
    seen = set()
    for line in raw.splitlines():
        m = re.search(r"^\d+:\s+([^\s:]+)\s+inet\s+([0-9.]+)/\d+", line)
        if m:
            _append_ip(items, seen, m.group(1), m.group(2))
            continue
    if items:
        return items
    current_iface = ""
    for line in raw.splitlines():
        m = re.match(r"^\d+:\s+([^\s:]+):", line)
        if m:
            current_iface = m.group(1)
            continue
        m = re.search(r"\binet\s+([0-9.]+)/\d+", line)
        if m and current_iface:
            _append_ip(items, seen, current_iface, m.group(1))
    return items


def get_ip_addresses() -> list:
    raw = run_cmd("ip -o -4 addr show up scope global")
    items = _parse_ip_output(raw)
    if items:
        items.sort(key=lambda item: _iface_priority(item["iface"]))
        return items
    raw = run_cmd("ip -4 addr show")
    items = _parse_ip_output(raw)
    if items:
        items.sort(key=lambda item: _iface_priority(item["iface"]))
        return items
    raw = run_cmd("hostname -I")
    items = []
    seen = set()
    for idx, ip in enumerate(raw.split(), start=1):
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
            _append_ip(items, seen, f"ip{idx}", ip)
    return items


def format_ip_addresses(items: list) -> str:
    if not items:
        return "-"
    return "\n".join(f"{item['iface']}: {item['ip']}" for item in items)


def get_ip() -> str:
    ip_items = get_ip_addresses()
    if ip_items:
        return format_ip_addresses(ip_items)
    ip = run_cmd("ip route get 1 | sed -n 's/.*src \\([0-9.]*\\).*/\\1/p' | head -n1")
    return ip or "-"


def get_uptime() -> str:
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            sec = int(float(f.read().split()[0]))
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        return f"{h}h {m}m {s}s"
    except Exception:
        return "-"


def get_public_config() -> dict:
    return {
        "ok": True,
        "config_path": config.CONFIG_PATH,
        "ui": {
            "font_size": config.UI_FONT_SIZE,
            "font_size_label": config.FONT_SIZE_LABELS.get(config.UI_FONT_SIZE, "中"),
            "font_zoom": config.UI_FONT_ZOOM,
            "font_size_options": [
                {"key": "small", "label": "小"},
                {"key": "medium", "label": "中"},
                {"key": "large", "label": "大"},
                {"key": "xlarge", "label": "特大"},
            ],
        },
        "accel": {
            "requested": {
                "preprocess": config.ACCEL_PREPROCESS,
                "geometry": config.ACCEL_GEOMETRY,
                "selector": config.ACCEL_SELECTOR,
            },
            "preprocess": get_preprocess_status(),
            "geometry": get_geometry_status(),
            "selector": get_selector_status(),
        },
        "stitch": {
            "engine": config.STITCH_ENGINE,
            "script_path": config.STITCH_SCRIPT,
            "input_dir": config.STITCH_INPUT_DIR,
            "output_dir": config.STITCH_OUTPUT_DIR,
            "input_url_prefix": config.STITCH_INPUT_URL_PREFIX,
            "output_url_prefix": config.STITCH_OUTPUT_URL_PREFIX,
            "max_canvas_pixels": config.MAX_STITCH_CANVAS_PIXELS,
            "multiband_max_canvas_pixels": config.MULTIBAND_MAX_STITCH_CANVAS_PIXELS,
            "postprocess_denoise_max_pixels": config.MAX_STITCH_DENOISE_PIXELS,
            "viewer": {
                "library": "pannellum",
                "version": "2.5.7",
                "mode": "partial_panorama",
                "haov": config.PANORAMA_HAOV,
                "vaov": config.PANORAMA_VAOV,
                "v_offset": config.PANORAMA_V_OFFSET,
                "initial_yaw": config.PANORAMA_INITIAL_YAW,
                "initial_pitch": config.PANORAMA_INITIAL_PITCH,
                "initial_hfov": config.PANORAMA_INITIAL_HFOV,
                "min_pitch": config.PANORAMA_MIN_PITCH,
                "max_pitch": config.PANORAMA_MAX_PITCH,
                "min_hfov": config.PANORAMA_MIN_HFOV,
                "max_hfov": config.PANORAMA_MAX_HFOV,
            },
            "camera": {
                "backend": config.CAMERA_BACKEND,
                "source": config.CAMERA_SOURCE,
                "source_text": config.camera_source_text(),
                "pixel_format": config.CAMERA_PIXEL_FORMAT,
                "rotation": config.CAMERA_ROTATION,
                "frame_width": config.CAMERA_FRAME_WIDTH,
                "frame_height": config.CAMERA_FRAME_HEIGHT,
                "fps": config.CAMERA_TARGET_FPS,
                "preview_max_dim": config.CAMERA_PREVIEW_MAX_DIM,
                "preview_jpeg_quality": config.CAMERA_PREVIEW_JPEG_QUALITY,
                "preview_fps": config.CAMERA_PREVIEW_FPS,
                "auto_interval_sec": config.CAMERA_AUTO_INTERVAL_SEC,
            },
        },
    }


def handle_get(path: str, query: dict | None = None):
    if path == "/api/config/public":
        return get_public_config(), 200
    if path == "/api/status":
        from app.routes.wifi_routes import get_wifi_status

        ip_items = get_ip_addresses()
        return {
            "hostname": run_cmd("hostname") or "-",
            "kernel": run_cmd("uname -r") or "-",
            "uptime": get_uptime(),
            "ip": format_ip_addresses(ip_items) if ip_items else get_ip(),
            "ip_list": ip_items,
            "wifi": get_wifi_status(),
            "backend": "ok",
        }, 200
    return None


def handle_post(path: str, payload: dict | None = None):
    if path == "/api/start-systemui":
        try:
            log("POST /api/start-systemui")
            subprocess.Popen(
                ["/bin/sh", config.SWITCH_SCRIPT],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"ok": True, "msg": "systemui switching started"}, 200
        except Exception as exc:
            log("error: " + str(exc))
            return {"ok": False, "msg": str(exc)}, 500
    return None
