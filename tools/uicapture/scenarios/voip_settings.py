"""voip-settings.html: SIP line settings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix, set_value

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

_TEXT_FIELDS = {
    "sip_domain": "SIP_Domain",
    "proxy_server": "proxy_server",
    "outbound_proxy": "outbound_proxy",
    "account": "account",
    "password": "password",
    "phone_number": "telephone_num",
}
_SWITCHES = {"dns_srv": "DNS_SRV", "line_enabled": "lineEnable", "pos_mode": "pos_mode_enable"}


async def update(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    for key, field in _TEXT_FIELDS.items():
        if key in inputs:
            await set_value(page, f"{pf}-voip_{field}_text", inputs[key])
    for key, switch in _SWITCHES.items():
        if key in inputs:
            element = f"{pf}-voip_{switch}_check"
            checked = await page.evaluate("(id) => document.getElementById(id).checked", element)
            if checked != inputs[key]:
                await click(page, element)  # the switches react to onclick
    if "bind_interface" in inputs:
        await click(page, f"Interface_{inputs['bind_interface']}")
    await click(page, f"{pf}-voip_save")


def _update(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.VOIP_SETTINGS,
        endpoint=Endpoint.VOIP_APPLY,
        call="voip.update",
        inputs=inputs,
        drive=update,
        **kw,
    )


SCENARIOS = [
    _update(
        "voip_phone_and_password",
        {"phone_number": "+39 0000 111222", "password": 's3cret pass&% "q" è'},
        notes="the page holds no phone number, so every save needs one",
    ),
    _update(
        "voip_phone_only",
        {"phone_number": "0000111222"},
        notes="untouched password: sent empty with donotset_pass 1",
    ),
    _update(
        "voip_servers_switches_bind",
        {
            "sip_domain": "sip.example.net",
            "proxy_server": "10.0.0.1",
            "outbound_proxy": "",
            "account": "Mario Rossi è&%",
            "phone_number": "+390000000001",
            "dns_srv": True,
            "line_enabled": False,
            "pos_mode": True,
            "bind_interface": "fwanat.tim.it",
        },
    ),
    _update("voip_refused_no_phone", {"dns_srv": True}, refused=True),
    _update(
        "voip_refused_no_proxy",
        {"proxy_server": "", "outbound_proxy": "", "phone_number": "0000111222"},
        refused=True,
    ),
    _update(
        "voip_refused_bad_domain",
        {"sip_domain": "bad_domain!", "phone_number": "0000111222"},
        refused=True,
    ),
    _update(
        "voip_refused_bad_proxy",
        {"proxy_server": "1.2.3.256", "phone_number": "0000111222"},
        refused=True,
    ),
    _update(
        "voip_refused_bad_outbound",
        {"outbound_proxy": "-bad.example.com", "phone_number": "0000111222"},
        refused=True,
    ),
]
