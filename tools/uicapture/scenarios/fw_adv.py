"""fw-adv.html: firewall level and VPN passthrough."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

_LEVEL_ITEM = {"high": "a", "middle": "b", "low": "c"}


async def set_checked(page: BrowserPage, element_id: str, *, checked: bool) -> None:
    """Flip a switch like a user would (fires ``change``)."""
    await page.evaluate(
        """([id, checked]) => {
            const el = document.getElementById(id);
            if (!el) throw new Error("no element #" + id);
            el.checked = checked;
            el.dispatchEvent(new Event("change", {bubbles: true}));
        }""",
        [element_id, checked],
    )


async def set_level(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    await click(page, f"{pf}-fw_level_{_LEVEL_ITEM[inputs['level']]}")
    await click(page, f"{pf}-fw_level_apply_btn")


async def set_vpn(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    if "enabled" in inputs:
        if inputs["enabled"]:  # the page has it on: flip off, then on again
            await set_checked(page, f"{pf}-vpn_switch", checked=False)
        await set_checked(page, f"{pf}-vpn_switch", checked=inputs["enabled"])
    await click(page, f"{pf}-vpn_apply_btn")


def _level(name: str, level: str, **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.FIREWALL,
        endpoint=Endpoint.FIREWALL_LEVEL,
        call="firewall.set_level",
        inputs={"level": level},
        drive=set_level,
        **kw,
    )


def _vpn(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.FIREWALL,
        endpoint=Endpoint.VPN_PASSTHROUGH,
        call="firewall.set_vpn_passthrough",
        inputs=inputs,
        drive=set_vpn,
        **kw,
    )


SCENARIOS = [
    _level("firewall_level_high", "high"),
    _level("firewall_level_low", "low"),
    _level("firewall_level_middle", "middle", notes="the page's current level"),
    _vpn("vpn_passthrough_off", {"enabled": False}),
    _vpn(
        "vpn_passthrough_unchanged",
        {},
        notes="untouched switch: the page's string value is resent",
    ),
    _vpn(
        "vpn_passthrough_on",
        {"enabled": True},
        notes="switch flipped off and on: isVpnEnable becomes the number 1",
    ),
]
