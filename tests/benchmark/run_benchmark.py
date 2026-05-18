#!/usr/bin/env python3
"""Initial benchmark runner for RK3588 stitching pipeline.

Outputs JSON with accelerator mode tags, preprocess timings, stitch timing,
CPU/memory snapshots, frame counts, and success/failure state.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import config
from app.geometry.cpu_geometry import CpuGeometryEngine
from app.geometry.opencl_geometry import OpenCLGeometryEngine
from app.preprocess.cpu_engine import CpuPreprocessEngine
from app.preprocess.rga_engine import RgaPreprocessEngine
from app.schemas import FramePacket
from app.selector.cpu_selector import CpuSelector
from app.selector.off_selector import OffSelector
from app.stitch_engine.opencv_engine import OpenCVStitchEngine
from app.stitch_engine.sequential_engine import SequentialPanoEngine
from app.services import metrics_service


def parse_args():
    parser = argparse.ArgumentParser(description="Run visual stitching benchmark")
    parser.add_argument("--input-dir", default="", help="Directory containing input images; synthetic frames are generated when empty")
    parser.add_argument("--output-json", default="", help="Report path; defaults to reports/benchmark_<timestamp>.json")
    parser.add_argument("--frames", type=int, default=2, help="Synthetic frame count or max loaded frames")
    parser.add_argument("--preprocess", choices=["cpu", "rga"], default=config.ACCEL_PREPROCESS)
    parser.add_argument(
        "--rga-lib",
        default="",
        help="Explicit libmyui_rga.so path for RGA benchmark runs; also accepted through MYUI_RGA_LIB",
    )
    parser.add_argument(
        "--require-rga",
        action="store_true",
        help="Exit non-zero if --preprocess rga does not actually run through the native wrapper",
    )
    parser.add_argument(
        "--feed-format",
        choices=["auto", "bgr", "nv12"],
        default="auto",
        help="FramePacket format fed into PreprocessEngine; auto uses nv12 for --preprocess rga synthetic/image inputs",
    )
    parser.add_argument("--geometry", choices=["cpu", "opencl"], default=config.ACCEL_GEOMETRY)
    parser.add_argument("--selector", choices=["off", "cpu_basic"], default=config.ACCEL_SELECTOR if config.ACCEL_SELECTOR in ("off", "cpu_basic") else "cpu_basic")
    parser.add_argument("--stitch-engine", choices=["opencv", "sequential"], default="opencv")
    parser.add_argument("--auto-crop", action="store_true")
    parser.add_argument(
        "--skip-stitch",
        action="store_true",
        help="Only benchmark preprocess/selector and skip OpenCV stitching; useful for accelerator mode smoke tests",
    )
    return parser.parse_args()


def create_synthetic_images(tmpdir: str, count: int) -> list[str]:
    count = max(2, int(count or 2))
    crop_w = 320
    crop_h = 240
    step = 160
    canvas_w = crop_w + step * (count - 1)
    canvas = np.zeros((crop_h, canvas_w, 3), dtype=np.uint8)
    rng = np.random.default_rng(3588)
    for _ in range(120):
        x = int(rng.integers(8, canvas_w - 8))
        y = int(rng.integers(8, crop_h - 8))
        color = tuple(int(v) for v in rng.integers(45, 255, size=3))
        cv2.circle(canvas, (x, y), int(rng.integers(3, 9)), color, -1)
    cv2.putText(canvas, "RK3588 RGA FIRST", (20, crop_h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)
    paths = []
    for idx in range(count):
        x0 = idx * step
        crop = canvas[:, x0:x0 + crop_w]
        path = os.path.join(tmpdir, f"synthetic_{idx + 1:02d}.jpg")
        cv2.imwrite(path, crop)
        paths.append(path)
    return paths


def load_input_images(input_dir: str, max_frames: int) -> list[str]:
    if not input_dir:
        return []
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
    paths = []
    for name in sorted(os.listdir(input_dir)):
        path = os.path.join(input_dir, name)
        if os.path.isfile(path) and Path(path).suffix.lower() in exts:
            paths.append(path)
        if len(paths) >= max(2, max_frames):
            break
    return paths


def bgr_to_nv12(bgr_image):
    """Convert a BGR ndarray to an NV12 ndarray shaped (h * 3 / 2, w)."""
    height, width = bgr_image.shape[:2]
    even_width = width - (width % 2)
    even_height = height - (height % 2)
    if even_width != width or even_height != height:
        bgr_image = bgr_image[:even_height, :even_width]
        height, width = bgr_image.shape[:2]
    i420 = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2YUV_I420).reshape(-1)
    y_size = width * height
    uv_size = y_size // 4
    y = i420[:y_size].reshape((height, width))
    u = i420[y_size:y_size + uv_size].reshape((height // 2, width // 2))
    v = i420[y_size + uv_size:y_size + uv_size * 2].reshape((height // 2, width // 2))
    uv = np.empty((height // 2, width), dtype=np.uint8)
    uv[:, 0::2] = u
    uv[:, 1::2] = v
    return np.vstack((y, uv))


def make_frame_packet(seq: int, timestamp: float, path: str, image, feed_format: str) -> FramePacket:
    height, width = image.shape[:2]
    if feed_format == "nv12":
        nv12 = bgr_to_nv12(image)
        frame_height = (nv12.shape[0] * 2) // 3
        frame_width = nv12.shape[1]
        return FramePacket(seq, timestamp, frame_width, frame_height, "NV12", path, nv12)
    return FramePacket(seq, timestamp, width, height, "BGR", path, image)


def make_preprocess(name: str, rga_lib: str = ""):
    return RgaPreprocessEngine(lib_path=rga_lib or None) if name == "rga" else CpuPreprocessEngine()


def make_geometry(name: str):
    return OpenCLGeometryEngine() if name == "opencl" else CpuGeometryEngine()


def make_selector(name: str):
    return CpuSelector() if name == "cpu_basic" else OffSelector()


def make_stitch_engine(name: str, geometry):
    opencv = OpenCVStitchEngine(geometry_engine=geometry)
    return SequentialPanoEngine(opencv) if name == "sequential" else opencv


def run():
    args = parse_args()
    report_dir = os.path.join(config.BASE_DIR, "reports")
    os.makedirs(report_dir, exist_ok=True)
    output_json = args.output_json or os.path.join(report_dir, f"benchmark_{time.strftime('%Y%m%d_%H%M%S')}.json")

    preprocess = make_preprocess(args.preprocess, args.rga_lib)
    geometry = make_geometry(args.geometry)
    selector = make_selector(args.selector)
    stitch_engine = make_stitch_engine(args.stitch_engine, geometry)

    before_snapshot = metrics_service.snapshot()
    before_stat = before_snapshot.get("proc_stat", {})
    start = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="myui_bench_") as tmpdir:
        input_paths = load_input_images(args.input_dir, args.frames)
        if len(input_paths) < 2:
            input_paths = create_synthetic_images(tmpdir, args.frames)
        feed_format = args.feed_format
        if feed_format == "auto":
            feed_format = "nv12" if args.preprocess == "rga" else "bgr"
        kept_paths = []
        preprocess_times = []
        selector_decisions = []
        last_keep_ts = 0.0
        last_keep_image = None

        processed_dir = os.path.join(tmpdir, "processed")
        os.makedirs(processed_dir, exist_ok=True)
        for seq, path in enumerate(input_paths, start=1):
            image = cv2.imread(path)
            if image is None:
                selector_decisions.append({"path": path, "keep": False, "reason": "read_failed"})
                continue
            simulated_interval = max(1.0, float(getattr(selector, "min_interval_sec", 0.0) or 0.0) + 0.1)
            packet = make_frame_packet(seq, seq * simulated_interval, path, image, feed_format)
            t0 = time.perf_counter()
            processed = preprocess.process_for_save(packet)
            preprocess_times.append((time.perf_counter() - t0) * 1000.0)
            decision = selector.decision(processed, {"last_keep_ts": last_keep_ts, "last_keep_image": last_keep_image})
            selector_decisions.append(decision)
            if decision.get("keep"):
                out = os.path.join(processed_dir, f"kept_{seq:03d}.jpg")
                cv2.imwrite(out, processed.bgr_image)
                kept_paths.append(out)
                last_keep_ts = processed.timestamp
                last_keep_image = processed.bgr_image.copy()

        stitch_total_ms = 0.0
        stitch_ok = False
        stitch_msg = "stitch skipped" if args.skip_stitch else "not enough kept frames"
        stitch_output = os.path.join(tmpdir, "benchmark_stitched.jpg")
        if args.skip_stitch:
            stitch_ok = True
        elif len(kept_paths) >= 2:
            t0 = time.perf_counter()
            stitch_ok, stitch_msg = stitch_engine.stitch(kept_paths, stitch_output, auto_crop=args.auto_crop)
            stitch_total_ms = (time.perf_counter() - t0) * 1000.0

        total_elapsed_ms = (time.perf_counter() - start) * 1000.0
        after_snapshot = metrics_service.snapshot()
        cpu_percent = metrics_service.cpu_percent_between(before_stat, after_snapshot.get("proc_stat", {}))
        memory_summary = metrics_service.summarize_memory(after_snapshot.get("meminfo", {}))
        pid_memory_summary = metrics_service.summarize_pid_memory(after_snapshot.get("pid_status", {}))

        preprocess_status = preprocess.status()
        geometry_status = geometry.status()
        selector_status = selector.status()
        stitch_status = stitch_engine.status()
        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": f"{preprocess_status.get('mode_tag')}+{selector_status.get('mode_tag')}",
            "preprocess_mode": preprocess_status.get("mode_tag"),
            "preprocess_actual": preprocess_status.get("actual"),
            "preprocess_reason": preprocess_status.get("reason"),
            "rga_wrapper_available": bool(preprocess_status.get("wrapper_available", False)),
            "rga_active_calls": int(preprocess_status.get("active_calls", 0) or 0),
            "rga_fallback_calls": int(preprocess_status.get("fallback_calls", 0) or 0),
            "geometry_mode": geometry_status.get("mode_tag"),
            "selector_mode": selector_status.get("mode_tag"),
            "stitch_mode": stitch_status.get("mode_tag"),
            "requested": {
                "preprocess": args.preprocess,
                "feed_format": feed_format,
                "geometry": args.geometry,
                "selector": args.selector,
                "stitch_engine": args.stitch_engine,
            },
            "actual": {
                "preprocess": preprocess_status.get("actual"),
                "geometry": geometry_status.get("actual"),
                "selector": selector_status.get("actual"),
                "stitch_engine": stitch_status.get("actual"),
            },
            "input_frame_count": len(input_paths),
            "kept_frame_count": len(kept_paths),
            "single_frame_preprocess_ms": preprocess_times[0] if preprocess_times else None,
            "preprocess_times_ms": preprocess_times,
            "avg_preprocess_ms": (sum(preprocess_times) / len(preprocess_times)) if preprocess_times else None,
            "stitch_total_ms": stitch_total_ms,
            "total_elapsed_ms": total_elapsed_ms,
            "cpu_percent": cpu_percent,
            "memory": memory_summary,
            "process_memory": pid_memory_summary,
            "thermal": after_snapshot.get("thermal", {}),
            "selector_decisions": selector_decisions,
            "stitch_ok": bool(stitch_ok),
            "stitch_msg": stitch_msg,
            "stitch_skipped": bool(args.skip_stitch),
            "auto_crop": bool(args.auto_crop),
            "preprocess_status": preprocess_status,
            "rga": {
                "requested": args.preprocess == "rga",
                "require_rga": bool(args.require_rga),
                "wrapper_available": bool(preprocess_status.get("wrapper_available", False)),
                "lib_path": preprocess_status.get("lib_path", ""),
                "lib_version": preprocess_status.get("lib_version", ""),
                "active_calls": int(preprocess_status.get("active_calls", 0) or 0),
                "fallback_calls": int(preprocess_status.get("fallback_calls", 0) or 0),
                "load_error": preprocess_status.get("load_error", ""),
            },
            "geometry_status": geometry_status,
            "selector_status": selector_status,
            "stitch_status": stitch_status,
            "snapshots": {
                "before": before_snapshot,
                "after": after_snapshot,
            },
        }

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    report["output_json"] = output_json
    metrics_service.print_console_summary(report)
    print(f"  output_json: {output_json}")
    if args.require_rga and args.preprocess == "rga" and report.get("preprocess_actual") != "rga":
        return 3
    return 0 if report.get("stitch_ok") else 2


if __name__ == "__main__":
    raise SystemExit(run())
