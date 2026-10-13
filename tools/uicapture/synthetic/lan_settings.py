"""lan-settings.html variants."""

from __future__ import annotations

from id525.endpoints import Page

from . import Variant, replace_once


def _bridge(html: str) -> str:
    return replace_once(html, "var modeSelectType_CFG = 0;", "var modeSelectType_CFG = 1;")


VARIANTS = {
    "lan-settings-bridge": Variant(
        Page.LAN_SETTINGS,
        _bridge,
        "bridge mode (modeSelectType_CFG = 1): the UI rewrites the DHCP range itself",
    ),
}
