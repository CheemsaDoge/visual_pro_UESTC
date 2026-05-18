#!/usr/bin/env python3
"""Small file logger used by the lightweight http.server backend."""
from __future__ import annotations

import time
from typing import Any

from app import config


def log(msg: Any) -> None:
    line = str(msg)
    try:
        with open(config.LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def log_event(component: str, message: str) -> None:
    log(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{component}] {message}")
