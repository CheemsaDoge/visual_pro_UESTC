#!/usr/bin/env python3
"""Storage helpers for stitch input/output and upload work files."""
from __future__ import annotations

import base64
import os
from urllib.parse import quote
from typing import List

from app import config


def safe_image_ext(name: str) -> str:
    ext = os.path.splitext(name or "")[1].lower()
    if ext in config.ALLOWED_IMAGE_EXTS:
        return ext
    return ".jpg"


def is_allowed_image_name(name: str) -> bool:
    return os.path.splitext(name or "")[1].lower() in config.ALLOWED_IMAGE_EXTS


def file_item(base_dir: str, url_prefix: str, filename: str) -> dict:
    path = os.path.join(base_dir, filename)
    stat = os.stat(path)
    return {
        "name": filename,
        "size": stat.st_size,
        "mtime": int(stat.st_mtime),
        "url": f"{url_prefix}{quote(filename)}",
    }


def camera_capture_file_item(filename: str) -> dict:
    return file_item(config.STITCH_INPUT_DIR, config.STITCH_INPUT_URL_PREFIX, filename)


def decode_image_payload(payload: dict, request_id: str, index: int) -> str:
    if not isinstance(payload, dict):
        raise ValueError("invalid image payload")
    raw_data = (payload.get("data") or "").strip()
    if not raw_data:
        raise ValueError(f"image {index} is empty")
    if "," in raw_data and ";base64" in raw_data.split(",", 1)[0]:
        raw_data = raw_data.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(raw_data)
    except Exception as exc:
        raise ValueError(f"image {index} base64 decode failed: {exc}") from exc
    if not image_bytes:
        raise ValueError(f"image {index} has no content")
    if len(image_bytes) > config.MAX_STITCH_IMAGE_BYTES:
        raise ValueError(f"image {index} is too large")
    filename = payload.get("name") or f"image_{index}.jpg"
    ext = safe_image_ext(filename)
    path = os.path.join(config.STITCH_WORK_DIR, f"{request_id}_{index}{ext}")
    with open(path, "wb") as f:
        f.write(image_bytes)
    return path


def list_stitch_input_images() -> List[dict]:
    return list_images(config.STITCH_INPUT_DIR, config.STITCH_INPUT_URL_PREFIX, reverse=False)


def list_stitch_output_images() -> List[dict]:
    return list_images(config.STITCH_OUTPUT_DIR, config.STITCH_OUTPUT_URL_PREFIX, reverse=True)


def list_images(base_dir: str, url_prefix: str, reverse: bool = False) -> List[dict]:
    items = []
    try:
        names = sorted(os.listdir(base_dir), reverse=reverse)
    except Exception:
        names = []
    for name in names:
        path = os.path.join(base_dir, name)
        if not os.path.isfile(path):
            continue
        if not is_allowed_image_name(name):
            continue
        try:
            items.append(file_item(base_dir, url_prefix, name))
        except Exception:
            continue
    return items


def clear_stitch_output_images() -> dict:
    deleted_count = 0
    errors = []
    try:
        names = os.listdir(config.STITCH_OUTPUT_DIR)
    except Exception as exc:
        return {"ok": False, "msg": str(exc), "deleted_count": 0}
    for name in names:
        path = os.path.join(config.STITCH_OUTPUT_DIR, name)
        if not os.path.isfile(path):
            continue
        if not is_allowed_image_name(name):
            continue
        try:
            os.remove(path)
            deleted_count += 1
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        return {
            "ok": False,
            "msg": "failed to remove some output files",
            "deleted_count": deleted_count,
            "errors": errors,
        }
    return {"ok": True, "msg": "cleared", "deleted_count": deleted_count}


def resolve_stitch_input_files(names: list) -> List[str]:
    if not isinstance(names, list) or len(names) < 2:
        raise ValueError("need at least two selected server images")
    paths = []
    seen = set()
    for index, raw_name in enumerate(names, start=1):
        name = (raw_name or "").strip()
        if not name:
            raise ValueError(f"selected server image {index} is empty")
        safe_name = os.path.basename(name)
        if safe_name != name:
            raise ValueError(f"selected server image {index} is invalid")
        if not is_allowed_image_name(safe_name):
            raise ValueError(f"selected server image {index} type is not supported")
        if safe_name in seen:
            continue
        path = os.path.join(config.STITCH_INPUT_DIR, safe_name)
        if not os.path.isfile(path):
            raise ValueError(f"selected server image {index} not found")
        seen.add(safe_name)
        paths.append(path)
    if len(paths) < 2:
        raise ValueError("need at least two selected server images")
    return paths
