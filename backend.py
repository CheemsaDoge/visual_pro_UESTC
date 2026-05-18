#!/usr/bin/env python3
"""Thin HTTP entrypoint for the RK3588 visual stitching GUI.

The legacy monolithic backend has been split into app/routes, app/services, and
pluggable engine modules.  This file now only owns HTTP transport, static file
serving, and streaming response framing.
"""
from __future__ import annotations

import json
import os
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from app import config
from app.routes import camera_routes, stitch_routes, system_routes, wifi_routes
from app.services.camera_service import get_camera_frame_jpeg, get_camera_session_status, get_camera_stream_frame
from app.utils.log import log, log_event

GET_ROUTES = (
    system_routes.handle_get,
    wifi_routes.handle_get,
    stitch_routes.handle_get,
    camera_routes.handle_get,
)
POST_ROUTES = (
    system_routes.handle_post,
    wifi_routes.handle_post,
    camera_routes.handle_post,
    stitch_routes.handle_post,
)


class Handler(SimpleHTTPRequestHandler):
    def send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_local_file(self, path: str) -> None:
        try:
            with open(path, "rb") as f:
                body = f.read()
        except Exception:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def send_file_from_prefix(self, req_path: str, prefix: str, base_dir: str) -> None:
        rel = req_path[len(prefix):]
        rel = unquote(rel).lstrip("/")
        if not rel:
            self.send_response(404)
            self.end_headers()
            return
        normalized = os.path.normpath(rel)
        if normalized.startswith("..") or os.path.isabs(normalized):
            self.send_response(403)
            self.end_headers()
            return
        base_abs = os.path.abspath(base_dir)
        target = os.path.abspath(os.path.join(base_abs, normalized))
        if target != base_abs and not target.startswith(base_abs + os.sep):
            self.send_response(403)
            self.end_headers()
            return
        if not os.path.isfile(target):
            self.send_response(404)
            self.end_headers()
            return
        self.send_local_file(target)

    def send_camera_stream(self, session_id: str = "") -> None:
        boundary = "frame"
        self.send_response(200)
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Connection", "close")
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        self.end_headers()
        last_frame_mark = 0.0
        try:
            while True:
                frame, active, current_session, _mtime, _seq = get_camera_stream_frame(session_id=session_id)
                if session_id and current_session and current_session != session_id:
                    break
                if not frame:
                    if not active:
                        break
                    time.sleep(0.01)
                    continue
                now = time.time()
                if now - last_frame_mark < 0.025:
                    time.sleep(0.005)
                    continue
                last_frame_mark = now
                header = (
                    f"--{boundary}\r\n"
                    "Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(frame)}\r\n\r\n"
                ).encode("utf-8")
                self.wfile.write(header)
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            log(f"camera stream closed: {exc}")

    def send_camera_frame_jpeg(self, session_id: str = "", after_seq: int = 0) -> None:
        frame, active, current_session, mtime, seq = get_camera_frame_jpeg(session_id=session_id)
        if session_id and current_session and current_session != session_id:
            self.send_response(404)
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if frame and after_seq > 0 and seq > 0 and seq <= after_seq and active:
            self.send_response(204)
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", "0")
            self.send_header("X-Frame-Seq", str(seq))
            self.end_headers()
            return
        if not frame:
            self.send_response(204 if active else 404)
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", "0")
            self.send_header("X-Frame-Seq", str(seq))
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(frame)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Frame-Seq", str(seq))
        if mtime > 0:
            self.send_header("Last-Modified", self.date_time_string(mtime))
        self.end_headers()
        self.wfile.write(frame)

    def read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except Exception:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(raw.decode("utf-8", errors="ignore"))
        except Exception:
            return {}

    def do_GET(self) -> None:
        split = urlsplit(self.path)
        path = split.path
        query = parse_qs(split.query or "")
        if path == "/":
            self.path = "/index.html"
            return super().do_GET()
        if path == "/api/camera/frame.jpg":
            session_id = (query.get("session_id", [""])[0] or "").strip()
            try:
                after_seq = int((query.get("after", ["0"])[0] or "0").strip())
            except Exception:
                after_seq = 0
            return self.send_camera_frame_jpeg(session_id=session_id, after_seq=max(0, after_seq))
        if path == "/api/camera/stream":
            session_id = (query.get("session_id", [""])[0] or "").strip()
            if session_id and session_id != (get_camera_session_status().get("session_id") or ""):
                return self.send_json({"ok": False, "msg": "camera session not found"}, status=404)
            return self.send_camera_stream(session_id=session_id)
        for route in GET_ROUTES:
            result = route(path, query)
            if result is not None:
                data, status = result
                return self.send_json(data, status=status)
        if config.STITCH_INPUT_URL_PREFIX != "/" and path.startswith(config.STITCH_INPUT_URL_PREFIX):
            return self.send_file_from_prefix(path, config.STITCH_INPUT_URL_PREFIX, config.STITCH_INPUT_DIR)
        if config.STITCH_OUTPUT_URL_PREFIX != "/" and path.startswith(config.STITCH_OUTPUT_URL_PREFIX):
            return self.send_file_from_prefix(path, config.STITCH_OUTPUT_URL_PREFIX, config.STITCH_OUTPUT_DIR)
        return super().do_GET()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        payload = None
        for route in POST_ROUTES:
            if payload is None:
                payload = self.read_json_body()
            result = route(path, payload)
            if result is not None:
                data, status = result
                return self.send_json(data, status=status)
        self.send_response(404)
        self.end_headers()


def main() -> None:
    log("backend start")
    log_event(
        "backend",
        f"port={config.PORT} preprocess={config.ACCEL_PREPROCESS} geometry={config.ACCEL_GEOMETRY} selector={config.ACCEL_SELECTOR}",
    )
    server = ThreadingHTTPServer(("0.0.0.0", config.PORT), Handler)
    print(f"serving at http://127.0.0.1:{config.PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
