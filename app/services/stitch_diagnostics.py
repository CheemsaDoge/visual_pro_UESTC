#!/usr/bin/env python3
"""In-memory, per-run diagnostics for user-visible stitch reports."""
from __future__ import annotations

import copy
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Iterator

from app.services.metrics_service import (
    cpu_percent_between,
    snapshot,
    summarize_memory,
    summarize_pid_memory,
)

_LOCK = threading.Lock()
_REPORTS: deque[dict[str, Any]] = deque(maxlen=30)


def _iso_time(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(timestamp))


def image_file_details(paths: list[str]) -> list[dict[str, Any]]:
    details = []
    for index, path in enumerate(paths, start=1):
        item: dict[str, Any] = {"index": index, "name": os.path.basename(path)}
        try:
            item["bytes"] = os.path.getsize(path)
        except OSError:
            item["bytes"] = None
        try:
            import cv2

            image = cv2.imread(path)
            if image is not None:
                item["width"] = int(image.shape[1])
                item["height"] = int(image.shape[0])
                item["channels"] = int(image.shape[2]) if len(image.shape) > 2 else 1
        except Exception as exc:
            item["inspect_error"] = str(exc)
        details.append(item)
    return details


class StitchDiagnostics:
    def __init__(self, request_id: str, source: str, image_paths: list[str], config_snapshot: dict[str, Any]) -> None:
        self.started_at = time.time()
        self.started_perf = time.perf_counter()
        self.process_cpu_start = time.process_time()
        self.start_snapshot = snapshot()
        self.report: dict[str, Any] = {
            "id": request_id,
            "started_at": _iso_time(self.started_at),
            "source": source,
            "status": "running",
            "input": {"count": len(image_paths), "files": image_file_details(image_paths)},
            "config": config_snapshot,
            "stages": [],
            "engine_detail": {},
        }

    @contextmanager
    def stage(self, name: str, **parameters: Any) -> Iterator[dict[str, Any]]:
        started = time.perf_counter()
        item: dict[str, Any] = {"name": name, "parameters": parameters}
        try:
            yield item
        except Exception as exc:
            item["error"] = str(exc)
            raise
        finally:
            item["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
            self.report["stages"].append(item)

    def finish(self, *, ok: bool, message: str, output_path: str = "", engine_detail: dict[str, Any] | None = None) -> dict[str, Any]:
        ended_at = time.time()
        end_snapshot = snapshot()
        wall_ms = (time.perf_counter() - self.started_perf) * 1000.0
        process_cpu_ms = (time.process_time() - self.process_cpu_start) * 1000.0
        cpu_percent = cpu_percent_between(self.start_snapshot.get("proc_stat", {}), end_snapshot.get("proc_stat", {}))
        process_capacity_percent = (process_cpu_ms * 100.0 / wall_ms) if wall_ms > 0 else None
        output: dict[str, Any] = {}
        if output_path:
            output["name"] = os.path.basename(output_path)
            try:
                output["bytes"] = os.path.getsize(output_path)
            except OSError:
                pass
            try:
                import cv2

                image = cv2.imread(output_path)
                if image is not None:
                    output["width"] = int(image.shape[1])
                    output["height"] = int(image.shape[0])
            except Exception as exc:
                output["inspect_error"] = str(exc)
        self.report.update({
            "status": "success" if ok else "failed",
            "message": message,
            "ended_at": _iso_time(ended_at),
            "total_elapsed_ms": round(wall_ms, 3),
            "output": output,
            "engine_detail": copy.deepcopy(engine_detail or {}),
            "resources": {
                "system_cpu_percent_approx": round(cpu_percent, 2) if cpu_percent is not None else None,
                "backend_process_cpu_capacity_percent_approx": round(process_capacity_percent, 2) if process_capacity_percent is not None else None,
                "backend_process_cpu_time_ms": round(process_cpu_ms, 3),
                "memory_before": summarize_memory(self.start_snapshot.get("meminfo", {})),
                "memory_after": summarize_memory(end_snapshot.get("meminfo", {})),
                "backend_memory_before": summarize_pid_memory(self.start_snapshot.get("pid_status", {})),
                "backend_memory_after": summarize_pid_memory(end_snapshot.get("pid_status", {})),
                "gpu_before": self.start_snapshot.get("gpu", {}),
                "gpu_after": end_snapshot.get("gpu", {}),
                "thermal_after": end_snapshot.get("thermal", {}),
                "note": "GPU is best-effort sysfs data; it is unavailable when the board kernel exposes no GPU counters.",
            },
        })
        with _LOCK:
            _REPORTS.appendleft(copy.deepcopy(self.report))
        return copy.deepcopy(self.report)


def list_reports(limit: int = 30) -> list[dict[str, Any]]:
    try:
        limit = max(1, min(int(limit), 30))
    except (TypeError, ValueError):
        limit = 30
    with _LOCK:
        return copy.deepcopy(list(_REPORTS)[:limit])


def get_report(report_id: str) -> dict[str, Any] | None:
    with _LOCK:
        for report in _REPORTS:
            if report.get("id") == report_id:
                return copy.deepcopy(report)
    return None
