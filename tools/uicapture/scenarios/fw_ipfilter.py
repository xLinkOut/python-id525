"""fw-ipfilter.html: IP filter rules (the real list is empty: edits use a synthetic page)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix, set_value
from .fw_adv import set_checked

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

RULES = "synthetic/fw-ipfilter-rules"


async def add_rule(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"{await platform_prefix(page)}-addNewBtn")
    await set_value(page, "ipf_lanipAddr", inputs["ip"])
    if inputs.get("ip_type") == "IPv6":
        await click(page, "ip_TypeSelect_v6")
    await click(page, "addIPBtn")


async def edit_rule(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"edit_rule_{inputs['instance']}")
    await set_value(page, "edit_ipf_lanipAddr", inputs["ip"])
    if "ip_type" in inputs:
        await click(page, f"edit_ip_TypeSelect_{'v6' if inputs['ip_type'] == 'IPv6' else 'v4'}")
    await click(page, "editIPBtn")


async def delete_rule(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"deleteItem_{inputs['instance']}")
    await click(page, "deleteIPBtn")


async def save_filter(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    if "enabled" in inputs:
        await set_checked(page, f"{pf}-ipfilter_switch", checked=inputs["enabled"])
    if "mode" in inputs:
        await click(
            page, f"{pf}-filterMode_{'white' if inputs['mode'] == 'whitelist' else 'black'}"
        )
    await click(page, f"{pf}-modal_alertBtn")


def _add(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.IP_FILTER,
        endpoint=Endpoint.IPFILTER_ADD,
        call="ip_filter.add_rule",
        inputs=inputs,
        drive=add_rule,
        **kw,
    )


def _edit(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.IP_FILTER,
        endpoint=Endpoint.IPFILTER_EDIT,
        call="ip_filter.edit_rule",
        inputs=inputs,
        drive=edit_rule,
        fixture=RULES,
        synthetic=True,
        **kw,
    )


def _save(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.IP_FILTER,
        endpoint=Endpoint.IPFILTER_SAVE,
        call="ip_filter.set_filter",
        inputs=inputs,
        drive=save_filter,
        **kw,
    )


SCENARIOS = [
    _add("ipfilter_add_ipv4", {"ip": "203.0.113.25"}),
    _add("ipfilter_add_ipv6", {"ip": "2001:db8:1::42", "ip_type": "IPv6"}),
    _add("ipfilter_add_ipv6_zone", {"ip": "fe80::1%eth0", "ip_type": "IPv6"}),
    _add("ipfilter_add_refused_empty", {"ip": ""}, refused=True),
    _add("ipfilter_add_refused_multicast", {"ip": "224.0.0.5"}, refused=True),
    _add("ipfilter_add_refused_loopback", {"ip": "127.0.0.1"}, refused=True),
    _add("ipfilter_add_refused_cidr", {"ip": "10.0.0.0/8"}, refused=True),
    _add("ipfilter_add_refused_broadcast", {"ip": "255.255.255.255"}, refused=True),
    _add("ipfilter_add_refused_ipv6_loopback", {"ip": "::1", "ip_type": "IPv6"}, refused=True),
    _add("ipfilter_add_refused_v4_as_v6", {"ip": "192.0.2.1", "ip_type": "IPv6"}, refused=True),
    _add(
        "ipfilter_add_refused_duplicate",
        {"ip": "192.0.2.10"},
        refused=True,
        fixture=RULES,
        synthetic=True,
    ),
    _edit("ipfilter_edit_ip", {"instance": 8, "ip": "2001:db8::77"}),
    _edit("ipfilter_edit_type", {"instance": "3", "ip": "2001:db8::99", "ip_type": "IPv6"}),
    _edit(
        "ipfilter_edit_refused_same_ip",
        {"instance": 11, "ip": "198.51.100.7"},
        refused=True,
        notes="the UI counts the rule's own address as a duplicate",
    ),
    Scenario(
        name="ipfilter_delete",
        page=Page.IP_FILTER,
        endpoint=Endpoint.IPFILTER_SAVE,
        call="ip_filter.delete_rule",
        inputs={"instance": 11},
        drive=delete_rule,
        fixture=RULES,
        synthetic=True,
    ),
    _save("ipfilter_enable_whitelist", {"enabled": True, "mode": "whitelist"}),
    _save("ipfilter_save_unchanged", {}),
    _save(
        "ipfilter_disable_keep_mode",
        {"enabled": False},
        fixture=RULES,
        synthetic=True,
        notes="page has the filter on in whitelist mode",
    ),
]
