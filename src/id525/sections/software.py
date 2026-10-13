"""Firmware update (``adm-sw`` page)."""

from __future__ import annotations

from typing import NoReturn

from ..endpoints import Endpoint, uses
from .base import Section


class SoftwareApi(Section):
    """Firmware update. Flashing is deliberately unsupported (can brick the router)."""

    @uses(Endpoint.UPLOAD_FILE, Endpoint.DO_UPGRADE)
    async def upgrade_firmware(self) -> NoReturn:
        """Not supported: flashing firmware can brick the router."""
        self._unsupported(Endpoint.DO_UPGRADE)

    @uses(Endpoint.ACS_UPDATE_CONFIRM)
    async def install_operator_update(self) -> NoReturn:
        """Not supported: installs operator firmware (irreversible)."""
        self._unsupported(Endpoint.ACS_UPDATE_CONFIRM)
