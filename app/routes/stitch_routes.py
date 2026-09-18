#!/usr/bin/env python3
"""Stitch JSON route dispatch."""
from __future__ import annotations

from app import config
from app.services.stitch_service import get_stitch_backend_status, run_image_stitch
from app.services.stitch_diagnostics import get_report, list_reports
from app.services.storage_service import clear_stitch_output_images, list_stitch_input_images, list_stitch_output_images
from app.utils.log import log


def handle_get(path: str, query: dict | None = None):
    if path == "/api/stitch/status":
        return get_stitch_backend_status(), 200
    if path == "/api/stitch/input-list":
        return {"ok": True, "input_dir": config.STITCH_INPUT_DIR, "files": list_stitch_input_images()}, 200
    if path == "/api/stitch/output-list":
        return {"ok": True, "output_dir": config.STITCH_OUTPUT_DIR, "files": list_stitch_output_images()}, 200
    if path == "/api/stitch/logs":
        report_id = str((query or {}).get("id", [""])[0] or "").strip()
        if report_id:
            report = get_report(report_id)
            if report is None:
                return {"ok": False, "msg": "stitch log not found"}, 404
            return {"ok": True, "report": report}, 200
        limit = (query or {}).get("limit", [30])[0]
        return {"ok": True, "reports": list_reports(limit)}, 200
    return None


def handle_post(path: str, payload: dict | None = None):
    payload = payload or {}
    if path == "/api/stitch/image":
        log("POST /api/stitch/image")
        result = run_image_stitch(payload)
        status = 200 if result.get("ok") else 500
        if result.get("msg") in ("need at least two images", "invalid image payload"):
            status = 400
        if "image " in (result.get("msg") or ""):
            status = 400
        if "selected server image" in (result.get("msg") or ""):
            status = 400
        return result, status
    if path == "/api/stitch/output-clear":
        log("POST /api/stitch/output-clear")
        result = clear_stitch_output_images()
        return result, 200 if result.get("ok") else 500
    return None
