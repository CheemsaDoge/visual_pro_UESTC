#!/usr/bin/env python3
"""Direct OpenCL geometry engine with bounded CPU fallback."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from app.geometry.base import GeometryEngine
from app.geometry.cpu_geometry import CpuGeometryEngine
from app.geometry.opencl_runtime import DirectOpenCLRuntime
from app.utils.log import log_event


class OpenCLGeometryEngine(GeometryEngine):
    requested_name = "opencl"

    def __init__(
        self,
        fallback: CpuGeometryEngine | None = None,
        runtime: DirectOpenCLRuntime | None = None,
    ) -> None:
        self.fallback = fallback or CpuGeometryEngine()
        self.runtime = runtime or DirectOpenCLRuntime()
        self.reason = ""
        self.last_error = ""
        self.active_calls = 0
        self.fallback_calls = 0
        self.remap_fallback_calls = 0
        runtime_status = self.runtime.status()
        self.platform_name = runtime_status.get("platform_name", "")
        self.device_name = runtime_status.get("device_name", "")
        self.runtime_available = bool(runtime_status.get("available", False))
        if self.runtime_available:
            self.actual_name = "opencl"
            self.mode_tag = "geometry_opencl_direct"
            self.reason = f"direct OpenCL runtime ready on {self.platform_name}/{self.device_name}"
            log_event("geometry", f"requested=opencl actual=opencl fallback=false reason={self.reason}")
        else:
            self.actual_name = "cpu"
            self.mode_tag = "opencl_fallback_cpu"
            self.reason = runtime_status.get("reason", "") or "direct OpenCL runtime unavailable"
            log_event("geometry", f"requested=opencl actual=cpu fallback=true reason={self.reason}")

    def warp_perspective(self, image: Any, matrix: Any, dsize: Tuple[int, int], **kwargs: Any) -> Any:
        if not self.runtime_available:
            self.fallback_calls += 1
            return self.fallback.warp_perspective(image, matrix, dsize, **kwargs)
        try:
            out = self.runtime.warp_perspective(image, matrix, dsize, **kwargs)
            self.active_calls += 1
            self.last_error = ""
            return out
        except Exception as exc:
            self.last_error = str(exc)
            self.fallback_calls += 1
            log_event("geometry", f"opencl warp fallback reason={self.last_error}")
            return self.fallback.warp_perspective(image, matrix, dsize, **kwargs)

    def remap(self, image: Any, map1: Any, map2: Any, **kwargs: Any) -> Any:
        self.remap_fallback_calls += 1
        if self.runtime_available:
            self.last_error = "direct OpenCL remap is not implemented yet"
            log_event("geometry", "opencl remap fallback reason=direct OpenCL remap is not implemented yet")
        return self.fallback.remap(image, map1, map2, **kwargs)

    def status(self) -> Dict[str, Any]:
        return {
            "requested": self.requested_name,
            "actual": self.actual_name,
            "mode_tag": self.mode_tag,
            "available": bool(self.runtime_available),
            "fallback": not self.runtime_available,
            "reason": self.reason,
            "platform_name": self.platform_name,
            "device_name": self.device_name,
            "active_calls": self.active_calls,
            "fallback_calls": self.fallback_calls,
            "remap_fallback_calls": self.remap_fallback_calls,
            "last_error": self.last_error,
            "runtime": self.runtime.status(),
            "fallback_engine": self.fallback.status(),
        }
