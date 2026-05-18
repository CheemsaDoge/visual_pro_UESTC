#!/usr/bin/env python3
"""Camera JSON route dispatch."""
from __future__ import annotations

from app.services.camera_service import (
    capture_camera_snapshot,
    get_camera_session_status,
    start_camera_session,
    stop_camera_session,
)
from app.utils.log import log


def handle_get(path: str, query: dict | None = None):
    if path == "/api/camera/status":
        return get_camera_session_status(), 200
    return None


def handle_post(path: str, payload: dict | None = None):
    payload = payload or {}
    if path == "/api/camera/start":
        log("POST /api/camera/start")
        result = start_camera_session(payload)
        status = 200 if result.get("ok") else 500
        if "mode must" in (result.get("msg") or ""):
            status = 400
        if "already running" in (result.get("msg") or ""):
            status = 409
        return result, status
    if path == "/api/camera/capture":
        log("POST /api/camera/capture")
        result = capture_camera_snapshot()
        status = 200 if result.get("ok") else 500
        if "manual mode" in (result.get("msg") or ""):
            status = 400
        if "not running" in (result.get("msg") or ""):
            status = 409
        return result, status
    if path == "/api/camera/stop":
        log("POST /api/camera/stop")
        result = stop_camera_session(payload)
        status = 200 if result.get("ok") else 500
        if "not started" in (result.get("msg") or ""):
            status = 409
        if "need at least two captured images" in (result.get("msg") or ""):
            status = 400
        return result, status
    return None
