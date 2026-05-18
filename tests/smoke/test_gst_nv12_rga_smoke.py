#!/usr/bin/env python3
"""Smoke: real /dev/video44 NV12 appsink frame into RGA preprocess."""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import config
from app.capture.gst_raw_nv12_capture import GstRawNv12Capture, OpenCvGstRawNv12Capture
from app.preprocess.rga_engine import RgaPreprocessEngine


def parse_args():
    parser = argparse.ArgumentParser(description="Capture raw NV12 from /dev/video44 and require RGA active")
    parser.add_argument("--device", default=config.camera_device_path() or "/dev/video44")
    parser.add_argument("--width", type=int, default=config.camera_effective_width())
    parser.add_argument("--height", type=int, default=config.camera_effective_height())
    parser.add_argument("--fps", type=int, default=config.camera_effective_fps())
    parser.add_argument("--frames", type=int, default=1)
    parser.add_argument("--timeout-sec", type=float, default=5.0)
    parser.add_argument("--rga-lib", default="")
    parser.add_argument("--require-rga", action="store_true", default=True)
    return parser.parse_args()


def print_packet(packet) -> None:
    print(f"pixel_format={packet.pixel_format}")
    print(f"width={packet.width}")
    print(f"height={packet.height}")
    print(f"stride_w={packet.stride_w}")
    print(f"stride_h={packet.stride_h}")
    print(f"buffer_size={packet.buffer_size}")
    print(f"timestamp_ns={packet.timestamp_ns}")
    print(f"source={packet.source}")
    print(f"stride_inferred={packet.stride_inferred}")
    print(f"stride_source={packet.meta.get('stride_source', '')}")


def print_preprocess(status) -> None:
    print(f"preprocess_mode={status.get('mode_tag')}")
    print(f"rga_wrapper_available={status.get('wrapper_available')}")
    print(f"rga_active_calls={status.get('active_calls')}")
    print(f"rga_fallback_calls={status.get('fallback_calls')}")
    print(f"require_rga={status.get('require_rga')}")
    print(f"last_error={status.get('last_error')}")


def run() -> int:
    args = parse_args()
    cap = None
    try:
        import cv2

        cap = OpenCvGstRawNv12Capture(
            cv2=cv2,
            device=args.device,
            width=args.width,
            height=args.height,
            fps=args.fps,
            pixel_format="NV12",
            timeout_sec=args.timeout_sec,
        )
        print(f"capture_impl=opencv-gstreamer opened={cap.isOpened()} error={cap.last_error}")
    except Exception as exc:
        print(f"capture_impl=opencv-gstreamer exception={exc}")
        cap = None
    if cap is None or not cap.isOpened():
        if cap is not None:
            cap.release()
        cap = GstRawNv12Capture(
            device=args.device,
            width=args.width,
            height=args.height,
            fps=args.fps,
            pixel_format="NV12",
            timeout_sec=args.timeout_sec,
        )
        print(f"capture_impl=gi-gstreamer opened={cap.isOpened()} error={cap.last_error}")
    if not cap.isOpened():
        print(f"open_camera_failed={cap.last_error}", file=sys.stderr)
        return 10
    engine = RgaPreprocessEngine(lib_path=args.rga_lib or None, require_rga=bool(args.require_rga))
    try:
        last_packet = None
        for seq in range(1, max(1, args.frames) + 1):
            packet = cap.read_packet(seq=seq, timestamp=time.time())
            print_packet(packet)
            if packet.pixel_format != "NV12":
                print(f"format_error={packet.pixel_format}", file=sys.stderr)
                return 12
            if packet.stride_w < packet.width or packet.stride_h < packet.height:
                print(f"stride_error={packet.stride_w}x{packet.stride_h}", file=sys.stderr)
                return 13
            engine.process_for_save(packet)
            last_packet = packet
        status = engine.status()
        print_preprocess(status)
        if last_packet is None:
            print("appsink_sample_error=no packet", file=sys.stderr)
            return 11
        if status.get("mode_tag") != "rga_active":
            return 20
        if int(status.get("active_calls", 0) or 0) <= 0:
            return 21
        if int(status.get("fallback_calls", 0) or 0) != 0:
            return 22
        if status.get("last_error") != "ok":
            return 23
        return 0
    except Exception as exc:
        print(f"smoke_failed={exc}", file=sys.stderr)
        status = engine.status()
        print_preprocess(status)
        return 30
    finally:
        cap.release()


if __name__ == "__main__":
    raise SystemExit(run())
