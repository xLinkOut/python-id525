"""fw-ddns.html: dynamic DNS (configuration comes from get_ddns_config)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix, set_value
from .fw_adv import set_checked

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

_SERVER_ITEM = {
    "dyndns.org": "a",
    "dtdns.com": "b",
    "zoneedit.com": "c",
    "no-ip.com": "d",
    "afraid.org": "e",
    "afraid.org-v2-basic": "e",
}
CONFIG = {
    "ddns_enable": "1",
    "ddns_host_name": "myhome.example.org",
    "ddns_user_name": "user.name_1",
    "ddns_password": "s3cr3t!pw",
    "ddns_url": "dyndns.org",
}
"""Invented get_ddns_config answer (the real one was never captured)."""


async def save(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await page.wait_for_function("() => typeof ddns_url !== 'undefined' && ddns_url !== ''")
    pf = await platform_prefix(page)
    if "enabled" in inputs:
        await set_checked(page, f"{pf}-dns_switch", checked=inputs["enabled"])
    if "server" in inputs:
        await click(page, f"{pf}-dns_server_{_SERVER_ITEM[inputs['server']]}")
    for key, element in (
        ("hostname", "host_name_input"),
        ("username", "username"),
        ("password", "pwd"),
    ):
        if key in inputs:
            await set_value(page, f"{pf}-{element}", inputs[key])
    await click(page, f"{pf}-ddns_save_btn")


def _ddns(
    name: str, inputs: dict[str, Any], config: dict[str, Any] | None = None, **kw: Any
) -> Scenario:
    return Scenario(
        name=name,
        page=Page.DDNS,
        endpoint=Endpoint.DDNS_SET,
        call="ddns.set_settings",
        inputs=inputs,
        drive=save,
        answers={"get_ddns_config": {**CONFIG, **(config or {})}},
        synthetic=True,
        **kw,
    )


SCENARIOS = [
    _ddns("ddns_change_hostname", {"hostname": "casa-2.example.net"}),
    _ddns("ddns_disable", {"enabled": False}),
    _ddns(
        "ddns_enable_afraid",
        {
            "enabled": True,
            "server": "afraid.org",
            "username": "me@example.com",
            "password": "Pa$$w0rd(x)",
        },
        {"ddns_enable": "0", "ddns_url": "no-ip.com"},
        notes="the UI lists afraid.org but sends afraid.org-v2-basic",
    ),
    _ddns(
        "ddns_unchanged_afraid",
        {},
        {"ddns_url": "afraid.org-v2-basic"},
        notes="untouched form: every value is resent as received",
    ),
    _ddns("ddns_refused_hostname_charset", {"hostname": "my_home.example.org"}, refused=True),
    _ddns("ddns_refused_hostname_length", {"hostname": "h" * 60 + ".org"}, refused=True),
    _ddns(
        "ddns_refused_empty_hostname",
        {"enabled": False, "hostname": ""},
        refused=True,
        notes="the host name is checked even when disabling",
    ),
    _ddns("ddns_refused_username_symbol", {"username": "50%off"}, refused=True),
    _ddns("ddns_refused_username_length", {"username": "u" * 64}, refused=True),
    _ddns("ddns_refused_password_symbol", {"password": "salt&pepper"}, refused=True),
    _ddns("ddns_refused_password_length", {"password": "p" * 64}, refused=True),
]
