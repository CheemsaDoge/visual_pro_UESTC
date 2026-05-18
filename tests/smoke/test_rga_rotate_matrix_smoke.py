#!/usr/bin/env python3
"""Smoke matrix for native RGA convert and rotate combinations."""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.preprocess.cpu_engine import CpuPreprocessEngine
from app.preprocess.rga_engine import RgaPreprocessEngine
from app.schemas import FramePacket


ROTATIONS = [
    ("none", 0),
    ("ccw90", 1),
    ("cw90", 2),
    ("180", 3),
]


def parse_args():
    parser = argparse.ArgumentParser(description="Collect native RGA rotate matrix diagnostics")
    parser.add_argument("--rga-lib", default="")
    parser.add_argument(
        "--sizes",
        default="320x240,640x480,1280x720,1920x1080",
        help="Comma-separated WxH list",
    )
    parser.add_argument("--require-all", action="store_true", help="Return nonzero if any matrix row fails")
    parser.add_argument("--skip-preprocess", action="store_true", help="Only call native functions directly")
    return parser.parse_args()


def parse_sizes(text: str) -> list[tuple[int, int]]:
    sizes: list[tuple[int, int]] = []
    for item in (text or "").split(","):
        item = item.strip().lower()
        if not item:
            continue
        w_text, h_text = item.split("x", 1)
        sizes.append((int(w_text), int(h_text)))
    return sizes


def rotated_dims(width: int, height: int, rotate_code: int) -> tuple[int, int]:
    if rotate_code in (1, 2):
        return height, width
    return width, height


def ptr(arr):
    return arr.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte))


def native_error(engine: RgaPreprocessEngine) -> str:
    return engine._native_last_error(engine.lib) if engine.lib is not None else engine.last_error


def configure_optional_symbols(lib) -> None:
    for name in ("myui_rga_bgr_rotate", "myui_rga_bgrx_rotate_to_bgr"):
        if not hasattr(lib, name):
            continue
        func = getattr(lib, name)
        func.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        func.restype = ctypes.c_int
    if hasattr(lib, "myui_rga_bgr_rotate_strided"):
        lib.myui_rga_bgr_rotate_strided.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        lib.myui_rga_bgr_rotate_strided.restype = ctypes.c_int


def print_row(op: str, width: int, height: int, rotate_name: str, rotate_code: int, dst_w: int, dst_h: int, ret: int, err: str) -> bool:
    ok = ret == 0
    print(
        f"matrix op={op} src={width}x{height} dst={dst_w}x{dst_h} "
        f"rotate={rotate_name}({rotate_code}) ok={ok} ret={ret} last_error={err}"
    )
    return ok


def run_native_row(engine: RgaPreprocessEngine, op: str, width: int, height: int, rotate_name: str, rotate_code: int) -> bool:
    import numpy as np

    lib = engine.lib
    if lib is None:
        print(f"matrix op={op} src={width}x{height} rotate={rotate_name} ok=False ret=-9999 last_error={engine.last_error}")
        return False
    dst_w, dst_h = rotated_dims(width, height, rotate_code)
    if op == "nv12_to_bgr":
        src = np.full((height * 3 // 2, width), 128, dtype=np.uint8)
        dst = np.empty((dst_h, dst_w, 3), dtype=np.uint8)
        ret = lib.myui_rga_nv12_to_bgr(ptr(src), width, height, ptr(dst), dst_w, dst_h, rotate_code)
    elif op == "bgr_rotate":
        if not hasattr(lib, "myui_rga_bgr_rotate"):
            print(f"matrix op={op} src={width}x{height} dst={dst_w}x{dst_h} rotate={rotate_name} ok=False ret=-9998 last_error=missing_symbol")
            return False
        src = np.zeros((height, width, 3), dtype=np.uint8)
        dst = np.empty((dst_h, dst_w, 3), dtype=np.uint8)
        ret = lib.myui_rga_bgr_rotate(ptr(src), width, height, ptr(dst), dst_w, dst_h, rotate_code)
    elif op == "bgr_rotate_strided":
        if not hasattr(lib, "myui_rga_bgr_rotate_strided"):
            print(f"matrix op={op} src={width}x{height} dst={dst_w}x{dst_h} rotate={rotate_name} ok=False ret=-9998 last_error=missing_symbol")
            return False
        src_wstride = ((width + 15) // 16) * 16
        dst_wstride = ((dst_w + 15) // 16) * 16
        src = np.zeros((height, src_wstride, 3), dtype=np.uint8)
        dst = np.empty((dst_h, dst_wstride, 3), dtype=np.uint8)
        ret = lib.myui_rga_bgr_rotate_strided(
            ptr(src),
            width,
            height,
            src_wstride,
            height,
            ptr(dst),
            dst_w,
            dst_h,
            dst_wstride,
            dst_h,
            rotate_code,
        )
        ok = int(ret) == 0
        print(
            f"matrix op={op} src={width}x{height} src_stride={src_wstride}x{height} "
            f"dst={dst_w}x{dst_h} dst_stride={dst_wstride}x{dst_h} "
            f"rotate={rotate_name}({rotate_code}) ok={ok} ret={int(ret)} last_error={native_error(engine)}"
        )
        return ok
    elif op == "bgrx_rotate_to_bgr":
        if not hasattr(lib, "myui_rga_bgrx_rotate_to_bgr"):
            print(f"matrix op={op} src={width}x{height} dst={dst_w}x{dst_h} rotate={rotate_name} ok=False ret=-9998 last_error=missing_symbol")
            return False
        src = np.zeros((height, width, 3), dtype=np.uint8)
        dst = np.empty((dst_h, dst_w, 3), dtype=np.uint8)
        ret = lib.myui_rga_bgrx_rotate_to_bgr(ptr(src), width, height, ptr(dst), dst_w, dst_h, rotate_code)
    else:
        raise ValueError(op)
    return print_row(op, width, height, rotate_name, rotate_code, dst_w, dst_h, int(ret), native_error(engine))


def run_preprocess_row(lib_path: str, width: int, height: int, rotate_name: str, rotate_code: int) -> bool:
    import numpy as np

    data = np.full((height * 3 // 2, width), 128, dtype=np.uint8)
    packet = FramePacket(
        seq=1,
        timestamp=time.time(),
        width=width,
        height=height,
        pixel_format="NV12",
        source="rotate_matrix",
        data=data,
        stride_w=width,
        stride_h=height,
    )
    engine = RgaPreprocessEngine(
        fallback=CpuPreprocessEngine(rotation=rotate_name),
        lib_path=lib_path or None,
        require_rga=True,
    )
    try:
        processed = engine.process_for_save(packet)
        meta = processed.meta
        ok = meta.get("mode_tag") == "rga_active" and not meta.get("post_rotate_cpu")
        ret = 0 if ok else -1
        err = meta.get("native_success_detail") or meta.get("native_transform_error") or meta.get("last_error")
        print(
            f"matrix op=preprocess_save src={width}x{height} dst={processed.width}x{processed.height} "
            f"rotate={rotate_name}({rotate_code}) ok={ok} ret={ret} "
            f"preprocess_mode={meta.get('mode_tag')} rga_transform={meta.get('rga_transform')} "
            f"post_rotate_cpu={meta.get('post_rotate_cpu')} last_error={err}"
        )
        return bool(ok)
    except Exception as exc:
        print(
            f"matrix op=preprocess_save src={width}x{height} rotate={rotate_name}({rotate_code}) "
            f"ok=False ret=-1 preprocess_mode={engine.status().get('mode_tag')} last_error={exc}"
        )
        return False


def run() -> int:
    args = parse_args()
    engine = RgaPreprocessEngine(lib_path=args.rga_lib or None, require_rga=True)
    status = engine.status()
    print(f"rga_wrapper_available={status.get('wrapper_available')}")
    print(f"rga_lib={status.get('lib_path')}")
    print(f"rga_version={status.get('lib_version')}")
    print(f"rga_last_error={status.get('last_error')}")
    if not engine.wrapper_available or engine.lib is None:
        return 10
    configure_optional_symbols(engine.lib)

    failures = 0
    for width, height in parse_sizes(args.sizes):
        for rotate_name, rotate_code in ROTATIONS:
            for op in ("nv12_to_bgr", "bgr_rotate", "bgr_rotate_strided", "bgrx_rotate_to_bgr"):
                if not run_native_row(engine, op, width, height, rotate_name, rotate_code):
                    failures += 1
            if not args.skip_preprocess and not run_preprocess_row(args.rga_lib, width, height, rotate_name, rotate_code):
                failures += 1
    print(f"matrix_failures={failures}")
    if args.require_all and failures:
        return 20
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
