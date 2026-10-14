"""Firewall level and VPN passthrough (``fw-adv`` page)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, Page, uses
from ..models import _raw
from ..parsers import extract_js_values
from .base import Section

if TYPE_CHECKING:
    from collections.abc import Mapping

_LEVEL_RE = re.compile(r"\bvar\s+level_apply\s*=\s*(\d+)\s*;")


class FirewallLevel(StrEnum):
    """Firewall level (the UI's dropdown; ``fw_lv`` 1 / 2 / 3 on the wire)."""

    LOW = "low"
    MIDDLE = "middle"
    HIGH = "high"

    @property
    def wire(self) -> int:
        """Return the ``fw_lv`` value the UI sends."""
        return _LEVEL_WIRE[self]


_LEVEL_WIRE = {FirewallLevel.LOW: 1, FirewallLevel.MIDDLE: 2, FirewallLevel.HIGH: 3}


@dataclass(frozen=True, slots=True, kw_only=True)
class FirewallSettings:
    """Firewall settings as shown by the ``fw-adv`` page."""

    level: FirewallLevel
    """Unknown values show as ``MIDDLE``, like in the UI."""
    vpn_passthrough: bool
    raw: Mapping[str, Any] = _raw()


def parse_firewall_page(html: str) -> FirewallSettings:
    """Parse the data the router embeds in ``fw-adv.html``."""
    values = extract_js_values(html)
    match = _LEVEL_RE.search(html)
    wire = int(match.group(1)) if match else None
    level = next((lv for lv, w in _LEVEL_WIRE.items() if w == wire), FirewallLevel.MIDDLE)
    return FirewallSettings(
        level=level,
        vpn_passthrough=values.get("vpn_status") != "0",  # UI: "0" is off, anything else on
        raw={**values, "level_apply": wire},
    )


class FirewallApi(Section):
    """Firewall level and VPN passthrough."""

    @uses(Page.FIREWALL)
    async def get_settings(self) -> FirewallSettings:
        """Return the firewall level and the VPN passthrough state."""
        return parse_firewall_page(await self._client._page(Page.FIREWALL))

    @uses(Endpoint.FIREWALL_LEVEL)
    async def set_level(self, level: FirewallLevel) -> None:
        """Set the firewall level (the UI's *Save* under *Firewall level*)."""
        level = FirewallLevel(level)

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "fw_lv": level.wire}

        await self._client._command(Endpoint.FIREWALL_LEVEL, body)

    @uses(Page.FIREWALL, Endpoint.VPN_PASSTHROUGH)
    async def set_vpn_passthrough(self, *, enabled: bool | None = None) -> None:
        """Enable / disable VPN passthrough (``None``: save the current state).

        Faithful to the UI's two encodings of ``isVpnEnable``: once the switch
        has been flipped it is the number ``1`` / ``0``; an untouched switch
        resends the page's own value (a string such as ``"1"``).
        """
        current = parse_firewall_page(await self._client._page(Page.FIREWALL))
        value: object = (
            current.raw.get("vpn_status", "1") if enabled is None else (1 if enabled else 0)
        )

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "isVpnEnable": value}

        await self._client._command(Endpoint.VPN_PASSTHROUGH, body)
