"""Firmware update (``adm-sw`` page)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

from ..endpoints import Endpoint, Page, uses
from ..exceptions import Id525CommandError, Id525ResponseError
from ..models import _raw
from ..parsers import clean_str, extract_js_values
from .base import Section

if TYPE_CHECKING:
    from collections.abc import Mapping

ACS_POLL_INTERVAL = 6.0
"""Seconds between two progress polls, as in the UI."""
ACS_MAX_POLLS = 20
"""The UI gives up after this many "inprogress" answers (about two minutes)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SoftwareInfo:
    """Firmware state as shown by the ``adm-sw`` page."""

    version: str | None
    build_date: str | None
    upgrade_status: str | None
    """Status of the last upgrade (e.g. ``Software Update failure``), if any."""
    raw: Mapping[str, Any] = _raw()


def parse_software_page(html: str) -> SoftwareInfo:
    """Parse the data the router embeds in ``adm-sw.html``."""
    values = extract_js_values(html)
    build_date = (values.get("fw_date") or "").replace("(IST)", "")
    return SoftwareInfo(
        version=clean_str(values.get("sw")),
        build_date=clean_str(build_date),
        upgrade_status=clean_str(values.get("upgrade_status")),
        raw=values,
    )


class SoftwareApi(Section):
    """Firmware update. Flashing is deliberately unsupported (can brick the router)."""

    @uses(Page.SOFTWARE)
    async def get_info(self) -> SoftwareInfo:
        """Return the firmware version and the state of the last upgrade."""
        return parse_software_page(await self._client._page(Page.SOFTWARE))

    @uses(Endpoint.ACS_CHECK_UPDATE, Endpoint.ACS_CHECK_UPDATE_STATUS)
    async def check_for_update(self, *, poll_interval: float = ACS_POLL_INTERVAL) -> str | None:
        """Ask the operator's update server (ACS) for new firmware; installs nothing.

        Mirrors the UI: start the check, then poll its progress every
        ``poll_interval`` seconds while the router answers ``inprogress``.
        Returns the available version, or ``None`` if the firmware is current.

        Note: this firmware's web UI keeps the "check for update" button
        disabled, so the router's answer has never been observed through it.
        """
        data = await self._client._call(Endpoint.ACS_CHECK_UPDATE)
        polls = 0
        while data.get("result") == "inprogress":
            if polls >= ACS_MAX_POLLS:
                msg = f"the update check was still in progress after {polls} polls"
                raise Id525ResponseError(msg)
            polls += 1
            await asyncio.sleep(poll_interval)
            data = await self._client._call(Endpoint.ACS_CHECK_UPDATE_STATUS)
        result = data.get("result")
        if result == "ready":
            return clean_str(data.get("AvailSoftwareVersion"))
        if result is False:
            raise Id525CommandError(Endpoint.ACS_CHECK_UPDATE, data.get("error"))
        msg = f"unexpected answer to the update check: {result!r}"
        raise Id525ResponseError(msg)

    @uses(Endpoint.UPLOAD_FILE, Endpoint.DO_UPGRADE)
    async def upgrade_firmware(self) -> NoReturn:
        """Not supported: flashing firmware can brick the router."""
        self._unsupported(Endpoint.DO_UPGRADE)

    @uses(Endpoint.ACS_UPDATE_CONFIRM)
    async def install_operator_update(self) -> NoReturn:
        """Not supported: installs operator firmware (irreversible)."""
        self._unsupported(Endpoint.ACS_UPDATE_CONFIRM)
