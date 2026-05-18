#!/usr/bin/env python3
"""Hardware/runtime metric collection for benchmark reports."""
from __future__ import annotations

import glob
import os
import time
from typing import Dict, Any


def read_proc_stat() -> Dict[str, Any]:
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            first = f.readline().strip().split()
        if not first or first[0] != "cpu":
            return {}
        values = [int(x) for x in first[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        return {"total": total, "idle": idle, "raw": values}
    except Exception as exc:
        return {"error": str(exc)}


def cpu_percent_between(before: Dict[str, Any], after: Dict[str, Any]) -> float | None:
    try:
        total_delta = int(after["total"]) - int(before["total"])
        idle_delta = int(after["idle"]) - int(before["idle"])
        if total_delta <= 0:
            return None
        return max(0.0, min(100.0, (1.0 - idle_delta / float(total_delta)) * 100.0))
    except Exception:
        return None


def read_meminfo() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.replace(":", "").split()
                if len(parts) >= 2:
                    try:
                        data[parts[0]] = int(parts[1])
                    except Exception:
                        data[parts[0]] = parts[1]
    except Exception as exc:
        data["error"] = str(exc)
    return data


def read_pid_status(pid: int | None = None) -> Dict[str, Any]:
    pid = int(pid or os.getpid())
    data: Dict[str, Any] = {"pid": pid}
    path = f"/proc/{pid}/status"
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                key, sep, value = line.partition(":")
                if sep:
                    data[key.strip()] = value.strip()
    except Exception as exc:
        data["error"] = str(exc)
    return data


def read_thermal() -> Dict[str, Any]:
    zones = []
    for zone_path in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        item: Dict[str, Any] = {"path": zone_path}
        try:
            with open(os.path.join(zone_path, "type"), "r", encoding="utf-8") as f:
                item["type"] = f.read().strip()
        except Exception:
            item["type"] = os.path.basename(zone_path)
        try:
            with open(os.path.join(zone_path, "temp"), "r", encoding="utf-8") as f:
                raw = f.read().strip()
            value = int(raw)
            item["temp_milli_c"] = value
            item["temp_c"] = value / 1000.0 if abs(value) > 1000 else float(value)
        except Exception as exc:
            item["error"] = str(exc)
        zones.append(item)
    return {"zones": zones}


def snapshot(pid: int | None = None) -> Dict[str, Any]:
    return {
        "timestamp": time.time(),
        "proc_stat": read_proc_stat(),
        "meminfo": read_meminfo(),
        "pid_status": read_pid_status(pid),
        "thermal": read_thermal(),
    }


def summarize_memory(meminfo: Dict[str, Any]) -> Dict[str, Any]:
    total = meminfo.get("MemTotal")
    available = meminfo.get("MemAvailable")
    if isinstance(total, int) and isinstance(available, int):
        used = total - available
        return {
            "mem_total_kb": total,
            "mem_available_kb": available,
            "mem_used_kb": used,
            "mem_used_percent": round(used * 100.0 / total, 2) if total else None,
        }
    return {}


def summarize_pid_memory(pid_status: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("VmRSS", "VmHWM", "VmSize", "Threads")
    return {key: pid_status.get(key) for key in keys if key in pid_status}


def print_console_summary(report: Dict[str, Any]) -> None:
    print("Benchmark summary:")
    for key in (
        "mode",
        "preprocess_mode",
        "preprocess_actual",
        "preprocess_reason",
        "rga_wrapper_available",
        "rga_active_calls",
        "rga_fallback_calls",
        "geometry_mode",
        "selector_mode",
        "input_frame_count",
        "kept_frame_count",
        "avg_preprocess_ms",
        "stitch_total_ms",
        "cpu_percent",
        "stitch_ok",
    ):
        if key in report:
            print(f"  {key}: {report[key]}")
