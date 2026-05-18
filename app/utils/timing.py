#!/usr/bin/env python3
"""Timing helpers for benchmark and services."""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


@dataclass
class TimerResult:
    name: str
    elapsed_ms: float = 0.0


@contextmanager
def timed(name: str = "") -> Iterator[TimerResult]:
    result = TimerResult(name=name)
    start = time.perf_counter()
    try:
        yield result
    finally:
        result.elapsed_ms = (time.perf_counter() - start) * 1000.0


def now_ms() -> float:
    return time.perf_counter() * 1000.0
