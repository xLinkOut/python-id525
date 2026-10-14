"""wifi-settings variants: flags the real dump has in one state only."""

from __future__ import annotations

import re

from id525.endpoints import Page

from . import Variant, replace_once

_MAIN_LIST_RE = re.compile(r'^(\s*var wifi_ssid_infos_(?:2|5) = ".*)$', re.M)


def _no_mlo(html: str) -> str:
    return replace_once(html, "var mloEnabled = 1;", "var mloEnabled = 0;")


def _wps_off(html: str) -> str:
    return replace_once(html, "var wpsStatus_cfg = '1';", "var wpsStatus_cfg = '0';")


def _wpa3_only(html: str) -> str:
    def to_wpa3(match: re.Match[str]) -> str:
        line = match.group(1)
        old = "&quot;Security_Mode&quot;:&quot;WPA2-PSK&quot;"
        if line.count(old) != 1:
            msg = "unexpected main network entry"
            raise ValueError(msg)
        return line.replace(old, "&quot;Security_Mode&quot;:&quot;WPA3-PSK&quot;")

    html, count = _MAIN_LIST_RE.subn(to_wpa3, html)
    if count != 2:
        msg = f"expected the two main network lists, found {count}"
        raise ValueError(msg)
    return html


def _mesh(html: str) -> str:
    html = replace_once(html, "var meshCtrlEnabled = 0;", "var meshCtrlEnabled = 1;")
    return _wps_off(_no_mlo(html))


VARIANTS = {
    "wifi-settings-no-mlo": Variant(Page.WIFI_SETTINGS, _no_mlo, "MLO disabled"),
    "wifi-settings-wps-off": Variant(Page.WIFI_SETTINGS, _wps_off, "WPS disabled"),
    "wifi-settings-wpa3": Variant(
        Page.WIFI_SETTINGS, _wpa3_only, "both main networks WPA3-PSK only"
    ),
    "wifi-settings-mesh": Variant(
        Page.WIFI_SETTINGS, _mesh, "mesh controller on, MLO off, WPS off"
    ),
}
