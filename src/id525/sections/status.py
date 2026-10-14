"""Data only found in the status pages (``net-status``).

``net_status_retrieve.cgi`` (:meth:`id525.Id525Client.get_network_status`)
returns the same ``net_info`` the ``net-status`` page embeds, but the page also
carries the SIM PIN state, which no JSON endpoint returns. (``client-status``
embeds nothing beyond ``client_status_retrieve.cgi``.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..endpoints import Page, uses
from ..models import _raw
from ..parsers import extract_js_values, parse_int
from .base import Section

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True, kw_only=True)
class SimPinStatus:
    """SIM PIN protection state (``net-status`` page).

    The router does not always fill these fields in (seen live): each value
    is ``None`` when the page leaves it blank. ``cellular.get_settings()``
    reliably reports ``pin_enabled`` and ``pin_retries`` (no PUK count).
    """

    pin_enabled: bool | None
    """Whether the SIM asks for a PIN at power-on."""
    pin_retries: int | None
    """PIN attempts left before the SIM wants the PUK."""
    puk_retries: int | None
    """PUK attempts left before the SIM is blocked for good."""
    raw: Mapping[str, Any] = _raw()


def parse_sim_pin_page(html: str) -> SimPinStatus:
    """Parse the SIM PIN state embedded in ``net-status.html``."""
    values = extract_js_values(html)
    pin = parse_int(values.get("pin_setting"))
    return SimPinStatus(
        pin_enabled=None if pin is None else pin == 1,
        pin_retries=parse_int(values.get("pinTryCount")),
        puk_retries=parse_int(values.get("pukTryCount")),
        raw={k: values[k] for k in ("pin_setting", "pinTryCount", "pukTryCount") if k in values},
    )


class StatusApi(Section):
    """Status-page data without a JSON endpoint."""

    @uses(Page.NET_STATUS)
    async def get_sim_pin_status(self) -> SimPinStatus:
        """Return whether the SIM PIN is enabled and the PIN / PUK attempts left."""
        return parse_sim_pin_page(await self._client._page(Page.NET_STATUS))
