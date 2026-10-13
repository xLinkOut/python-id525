"""Cellular settings (``cellular-settings`` page) and SIM PIN handling."""

from __future__ import annotations

from typing import NoReturn

from ..endpoints import Endpoint, uses
from .base import Section


class CellularApi(Section):
    """Network mode, roaming, operator selection, APNs; SIM PIN (unsupported)."""

    @uses(Endpoint.PIN_ENTER)
    async def enter_pin(self) -> NoReturn:
        """Not supported by policy: wrong PINs burn SIM retries."""
        self._unsupported(Endpoint.PIN_ENTER)

    @uses(Endpoint.PUK_ENTER)
    async def enter_puk(self) -> NoReturn:
        """Not supported by policy: wrong PUKs lock the SIM permanently."""
        self._unsupported(Endpoint.PUK_ENTER)

    @uses(Endpoint.CHANGE_PIN)
    async def change_pin(self) -> NoReturn:
        """Not supported by policy (SIM PIN management)."""
        self._unsupported(Endpoint.CHANGE_PIN)

    @uses(Endpoint.PIN_LOCK)
    async def set_pin_lock(self) -> NoReturn:
        """Not supported by policy (SIM PIN management)."""
        self._unsupported(Endpoint.PIN_LOCK)
