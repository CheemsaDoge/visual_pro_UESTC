#!/usr/bin/env python3
"""Stitch orchestration: upload/server-file resolution + engine dispatch."""
from __future__ import annotations

import os
import subprocess
import time
import uuid
from urllib.parse import quote
from typing import List, Tuple

from app import config
from app.services.geometry_service import get_geometry_engine, get_geometry_status
from app.services.storage_service import decode_image_payload, resolve_stitch_input_files
from app.stitch_engine.opencv_engine import OpenCVStitchEngine
from app.stitch_engine.scans_engine import ScansStitchEngine
from app.stitch_engine.sequential_engine import SequentialPanoEngine
from app.utils.log import log_event

_ENGINE = None


def tail_text(text, max_len: int = 360) -> str:
    if text is None:
        return ""
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    return text[-max_len:]


def create_stitch_engine():
    geometry_engine = get_geometry_engine()
    if config.STITCH_ENGINE == "sequential":
        return SequentialPanoEngine(
            geometry_engine=geometry_engine,
            fallback=OpenCVStitchEngine(geometry_engine=geometry_engine),
        )
    if config.STITCH_ENGINE == "scans":
        return ScansStitchEngine()
    return OpenCVStitchEngine(geometry_engine=geometry_engine)


def get_stitch_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_stitch_engine()
        log_event("stitch", f"requested={config.STITCH_ENGINE} actual={_ENGINE.actual_name} mode={_ENGINE.mode_tag}")
    return _ENGINE


def get_stitch_backend_status() -> dict:
    info = {
        "ok": True,
        "enabled": False,
        "engine": config.STITCH_ENGINE,
        "script_path": config.STITCH_SCRIPT if config.STITCH_ENGINE == "script" else "",
        "output_url_prefix": config.STITCH_OUTPUT_URL_PREFIX,
        "input_url_prefix": config.STITCH_INPUT_URL_PREFIX,
        "camera_source": config.CAMERA_SOURCE,
        "camera_source_text": config.camera_source_text(),
        "camera_backend": config.CAMERA_BACKEND,
        "camera_pixel_format": config.CAMERA_PIXEL_FORMAT,
        "camera_rotation": config.CAMERA_ROTATION,
        "camera_preview_max_dim": config.CAMERA_PREVIEW_MAX_DIM,
        "camera_preview_jpeg_quality": config.CAMERA_PREVIEW_JPEG_QUALITY,
        "camera_preview_fps": config.CAMERA_PREVIEW_FPS,
        "camera_auto_interval_sec": config.CAMERA_AUTO_INTERVAL_SEC,
        "geometry": get_geometry_status(),
    }
    if config.STITCH_ENGINE == "script":
        if os.path.isfile(config.STITCH_SCRIPT):
            info["enabled"] = True
            info["runner"] = config.STITCH_SCRIPT_PYTHON if config.STITCH_SCRIPT.lower().endswith(".py") else "direct"
            return info
        info["msg"] = f"stitch script not found: {config.STITCH_SCRIPT}"
        return info

    engine_status = get_stitch_engine().status()
    info.update({
        "enabled": bool(engine_status.get("available", True)),
        "engine_status": engine_status,
        "actual_engine": engine_status.get("actual"),
        "stitch_mode": engine_status.get("mode_tag"),
    })
    if not info["enabled"]:
        info["msg"] = engine_status.get("reason") or "stitch engine unavailable"
    try:
        import numpy as np

        info["numpy"] = getattr(np, "__version__", "unknown")
    except Exception as exc:
        info["numpy"] = f"unavailable: {exc}"
    return info


def run_stitch_script(image_paths: List[str], output_path: str, auto_crop: bool = False) -> Tuple[bool, str]:
    if not os.path.isfile(config.STITCH_SCRIPT):
        return False, f"stitch script not found: {config.STITCH_SCRIPT}"
    cmd = [config.STITCH_SCRIPT_PYTHON, config.STITCH_SCRIPT] if config.STITCH_SCRIPT.lower().endswith(".py") else [config.STITCH_SCRIPT]
    cmd.extend(["--output", output_path])
    cmd.append("--auto-crop" if auto_crop else "--no-auto-crop")
    cmd.extend(image_paths)
    try:
        proc = subprocess.run(
            cmd,
            cwd=config.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=config.STITCH_SCRIPT_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return False, f"stitch script timeout ({config.STITCH_SCRIPT_TIMEOUT_SEC}s)"
    except Exception as exc:
        return False, f"stitch script run failed: {exc}"
    if proc.returncode != 0:
        detail = tail_text(proc.stderr) or tail_text(proc.stdout) or "unknown error"
        return False, f"stitch script failed (code={proc.returncode}): {detail}"
    if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
        return True, "ok"
    return False, "stitch script completed but output file was not generated"


def stitch_image_files(image_paths: List[str], output_path: str, auto_crop: bool = False) -> Tuple[bool, str]:
    return get_stitch_engine().stitch(image_paths, output_path, auto_crop=auto_crop)


def run_image_stitch(payload: dict) -> dict:
    status = get_stitch_backend_status()
    if not status.get("enabled"):
        return {"ok": False, "msg": status.get("msg") or "stitch backend unavailable"}

    images = payload.get("images") if isinstance(payload, dict) else None
    server_files = payload.get("server_files") if isinstance(payload, dict) else None
    auto_crop = bool(payload.get("auto_crop")) if isinstance(payload, dict) else False
    request_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    image_paths: List[str] = []
    cleanup_after_run = False

    if isinstance(images, list) and len(images) >= 2:
        try:
            for index, image_payload in enumerate(images, start=1):
                image_paths.append(decode_image_payload(image_payload, request_id, index))
            cleanup_after_run = True
        except ValueError as exc:
            return {"ok": False, "msg": str(exc)}
    elif isinstance(server_files, list) and len(server_files) >= 2:
        try:
            image_paths = resolve_stitch_input_files(server_files)
        except ValueError as exc:
            return {"ok": False, "msg": str(exc)}
    else:
        return {"ok": False, "msg": "need at least two images"}

    output_name = f"stitched_{request_id}.jpg"
    output_path = os.path.join(config.STITCH_OUTPUT_DIR, output_name)
    try:
        if config.STITCH_ENGINE == "script":
            ok, msg = run_stitch_script(image_paths, output_path, auto_crop=auto_crop)
        else:
            ok, msg = stitch_image_files(image_paths, output_path, auto_crop=auto_crop)
    finally:
        if cleanup_after_run:
            for path in image_paths:
                try:
                    os.remove(path)
                except Exception:
                    pass
    if not ok:
        return {"ok": False, "msg": msg}
    return {
        "ok": True,
        "msg": "stitched",
        "auto_crop": auto_crop,
        "image_count": len(image_paths),
        "result_name": output_name,
        "result_url": f"{config.STITCH_OUTPUT_URL_PREFIX}{quote(output_name)}",
        "engine": config.STITCH_ENGINE,
        "actual_engine": get_stitch_engine().actual_name if config.STITCH_ENGINE != "script" else "script",
    }
