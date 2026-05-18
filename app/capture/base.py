#!/usr/bin/env python3
"""Capture adapter base classes."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Tuple


class CaptureDevice(ABC):
    @abstractmethod
    def isOpened(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def read(self) -> Tuple[bool, Any]:
        raise NotImplementedError

    @abstractmethod
    def release(self) -> None:
        raise NotImplementedError
