"""All capture scenarios, by page."""

from __future__ import annotations

from . import adm_backup, lan_settings
from .base import Scenario

SCENARIOS: list[Scenario] = [*lan_settings.SCENARIOS, *adm_backup.SCENARIOS]

__all__ = ["SCENARIOS", "Scenario"]
