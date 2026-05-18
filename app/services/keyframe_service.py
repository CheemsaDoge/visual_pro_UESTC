#!/usr/bin/env python3
"""Keyframe selector factory and shared status."""
from __future__ import annotations

from app import config
from app.selector.cpu_selector import CpuSelector
from app.selector.off_selector import OffSelector
from app.selector.rknn_selector import RknnSelector
from app.utils.log import log_event

_SELECTOR = None


def create_selector():
    requested = config.ACCEL_SELECTOR
    if requested == "cpu_basic":
        selector = CpuSelector()
    elif requested == "rknn":
        selector = RknnSelector()
    else:
        selector = OffSelector()
    log_event("selector", f"requested={requested} actual={selector.actual_name} mode={selector.mode_tag}")
    return selector


def get_selector():
    global _SELECTOR
    if _SELECTOR is None:
        _SELECTOR = create_selector()
    return _SELECTOR


def get_selector_status() -> dict:
    return get_selector().status()
