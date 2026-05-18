#!/usr/bin/env python3
"""Preprocess engine factory."""
from __future__ import annotations

from app import config
from app.preprocess.cpu_engine import CpuPreprocessEngine
from app.preprocess.rga_engine import RgaPreprocessEngine
from app.utils.log import log_event

_ENGINE = None


def create_preprocess_engine():
    requested = config.ACCEL_PREPROCESS
    if requested == "rga":
        engine = RgaPreprocessEngine()
    else:
        engine = CpuPreprocessEngine()
        log_event("preprocess", "requested=cpu actual=cpu fallback=false")
    return engine


def get_preprocess_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_preprocess_engine()
    return _ENGINE


def get_preprocess_status() -> dict:
    return get_preprocess_engine().status()
