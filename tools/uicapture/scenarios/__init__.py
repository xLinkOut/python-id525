"""All capture scenarios: every module in this package exposing ``SCENARIOS``."""

from __future__ import annotations

import importlib
import pkgutil

from .base import Scenario

SCENARIOS: list[Scenario] = []
for _module in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
    if _module.name != "base":
        SCENARIOS += importlib.import_module(f"{__name__}.{_module.name}").SCENARIOS

_names = [s.name for s in SCENARIOS]
if len(_names) != len(set(_names)):
    msg = f"duplicate scenario names: {sorted({n for n in _names if _names.count(n) > 1})}"
    raise ValueError(msg)

__all__ = ["SCENARIOS", "Scenario"]
