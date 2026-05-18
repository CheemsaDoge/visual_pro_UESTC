#!/usr/bin/env python3
"""Geometry engine factory."""
from __future__ import annotations

from app import config
from app.geometry.cpu_geometry import CpuGeometryEngine
from app.geometry.opencl_geometry import OpenCLGeometryEngine
from app.utils.log import log_event

_ENGINE = None


def create_geometry_engine():
    requested = config.ACCEL_GEOMETRY
    if requested == "opencl":
        engine = OpenCLGeometryEngine()
    else:
        engine = CpuGeometryEngine()
        log_event("geometry", "requested=cpu actual=cpu fallback=false")
    return engine


def get_geometry_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_geometry_engine()
    return _ENGINE


def get_geometry_status() -> dict:
    return get_geometry_engine().status()
