#!/usr/bin/env python3
"""GStreamer capture pipeline helper."""
from __future__ import annotations


def build_nv12_to_bgr_pipeline(device: str, width: int, height: int, fps: int, pixel_format: str = "NV12") -> str:
    pixel_format = (pixel_format or "NV12").upper()
    return (
        f"v4l2src device={device} ! "
        f"video/x-raw,format={pixel_format},width={int(width)},height={int(height)},framerate={int(fps)}/1 ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    )


def build_raw_nv12_pipeline(device: str, width: int, height: int, fps: int, pixel_format: str = "NV12") -> str:
    pixel_format = (pixel_format or "NV12").upper()
    return (
        f"v4l2src device={device} ! "
        f"video/x-raw,format={pixel_format},width={int(width)},height={int(height)},framerate={int(fps)}/1 ! "
        "queue leaky=downstream max-size-buffers=1 ! "
        "appsink name=sink drop=true max-buffers=1 sync=false"
    )
