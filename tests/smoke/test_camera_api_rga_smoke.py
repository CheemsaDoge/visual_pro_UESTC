#!/usr/bin/env python3
"""Smoke camera service preview/save with raw NV12 capture and required RGA."""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.camera_service import capture_camera_snapshot, get_camera_session_status, start_camera_session, stop_camera_session


def parse_args():
    parser = argparse.ArgumentParser(description="Run camera preview/save smoke with raw NV12 backend")
    parser.add_argument("--capture-backend", default="v4l2ctl_nv12_raw", choices=["v4l2ctl_nv12_raw", "gst_nv12_raw"])
    parser.add_argument("--wait-sec", type=float, default=5.0)
    parser.add_argument("--require-rga", action="store_true", default=True)
    parser.add_argument("--captures", type=int, default=1)
    return parser.parse_args()


def print_status(prefix: str, data: dict) -> None:
    print(f"{prefix}.capture_backend={data.get('capture_backend')}")
    print(f"{prefix}.last_frame_format={data.get('last_frame_format')}")
    print(f"{prefix}.last_frame_width={data.get('last_frame_width')}")
    print(f"{prefix}.last_frame_height={data.get('last_frame_height')}")
    print(f"{prefix}.last_frame_buffer_size={data.get('last_frame_buffer_size')}")
    print(f"{prefix}.last_frame_stride_w={data.get('last_frame_stride_w')}")
    print(f"{prefix}.last_frame_stride_h={data.get('last_frame_stride_h')}")
    print(f"{prefix}.preview={data.get('last_preview_preprocess')}")
    print(f"{prefix}.save={data.get('last_save_preprocess')}")
    preprocess = data.get("preprocess") or {}
    print(f"{prefix}.preprocess_mode={preprocess.get('mode_tag')}")
    print(f"{prefix}.rga_wrapper_available={preprocess.get('wrapper_available')}")
    print(f"{prefix}.rga_active_calls={preprocess.get('active_calls')}")
    print(f"{prefix}.rga_fallback_calls={preprocess.get('fallback_calls')}")
    print(f"{prefix}.last_error={preprocess.get('last_error')}")


def run() -> int:
    args = parse_args()
    started = start_camera_session({
        "mode": "manual",
        "capture_backend": args.capture_backend,
        "require_rga": bool(args.require_rga),
    })
    print(f"start={started}")
    if not started.get("ok"):
        return 10
    try:
        deadline = time.time() + max(0.5, args.wait_sec)
        status = get_camera_session_status()
        while time.time() < deadline:
            status = get_camera_session_status()
            preview = status.get("last_preview_preprocess") or {}
            if status.get("last_frame_format") == "NV12" and preview.get("preprocess_mode") == "rga_active":
                break
            if status.get("error"):
                break
            time.sleep(0.1)
        print_status("status_before_capture", status)
        if status.get("last_frame_format") != "NV12":
            return 11
        if bool(args.require_rga) and (status.get("last_preview_preprocess") or {}).get("preprocess_mode") != "rga_active":
            return 12
        capture_result = {}
        for _idx in range(max(1, args.captures)):
            capture_result = capture_camera_snapshot()
            print(f"capture={capture_result}")
            if not capture_result.get("ok"):
                return 20
        status = get_camera_session_status()
        print_status("status_after_capture", status)
        save = status.get("last_save_preprocess") or {}
        if save.get("preprocess_mode") != "rga_active":
            return 21
        if int(save.get("rga_fallback_calls", 0) or 0) != 0:
            return 22
        return 0
    finally:
        stopped = stop_camera_session({"auto_crop": False})
        print(f"stop={stopped}")


if __name__ == "__main__":
    raise SystemExit(run())
