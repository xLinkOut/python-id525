"""lan-settings.html: DHCP reservations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix, set_value

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage


async def _position(page: BrowserPage, index: int) -> int:
    position: int = await page.evaluate(
        "(index) => staticAddrList.findIndex((e) => e.index == index)", index
    )
    if position < 0:
        msg = f"no reservation with index {index} on the page"
        raise LookupError(msg)
    return position


async def add_reservation(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"{await platform_prefix(page)}-addBtn")
    await set_value(page, "addDevNameText", inputs["name"])
    await set_value(page, "addIPText", inputs["ip"])
    await set_value(page, "addMACText", inputs["mac"])
    await click(page, "addAddr_modal_btn")


async def modify_reservation(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"staticAddrEdit{await _position(page, inputs['index'])}")
    for key, element in (("name", "editDevNameText"), ("ip", "editIPText"), ("mac", "editMACText")):
        if key in inputs:
            await set_value(page, element, inputs[key])
    await click(page, "editAddrBtn")


async def delete_reservation(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"staticAddrDel{await _position(page, inputs['index'])}")
    await click(page, "_dialog_modal_btn")  # the confirmation dialog's "Delete"


def _add(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.LAN_SETTINGS,
        endpoint=Endpoint.DHCP_RESERVATION_ADD,
        call="lan.add_dhcp_reservation",
        inputs=inputs,
        drive=add_reservation,
        **kw,
    )


def _modify(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.LAN_SETTINGS,
        endpoint=Endpoint.DHCP_RESERVATION_MODIFY,
        call="lan.modify_dhcp_reservation",
        inputs=inputs,
        drive=modify_reservation,
        **kw,
    )


SCENARIOS = [
    _add("dhcp_add", {"name": "printer", "ip": "192.168.224.50", "mac": "02:00:5E:00:00:AA"}),
    _add(
        "dhcp_add_unicode_name",
        {"name": "Stampante 2º piano ü", "ip": "192.168.224.219", "mac": "02:00:5e:00:00:ab"},
        notes="non-ASCII and spaces are allowed by the UI; last address of the pool",
    ),
    _add(
        "dhcp_add_refused_outside_pool",
        {"name": "nas", "ip": "192.168.224.250", "mac": "02:00:5e:00:00:ac"},
        refused=True,
    ),
    _add(
        "dhcp_add_refused_bad_mac",
        {"name": "nas", "ip": "192.168.224.60", "mac": "02-00-5e-00-00-ac"},
        refused=True,
    ),
    _add(
        "dhcp_add_refused_name_charset",
        {"name": "nas_1", "ip": "192.168.224.60", "mac": "02:00:5e:00:00:ac"},
        refused=True,
    ),
    _add(
        "dhcp_add_refused_duplicate_mac",
        {"name": "nas", "ip": "192.168.224.60", "mac": "02:00:5E:00:00:01"},
        refused=True,
        notes="MAC comparison is case-insensitive",
    ),
    _modify("dhcp_modify_ip", {"index": 2, "ip": "192.168.224.21"}),
    _modify(
        "dhcp_modify_all",
        {"index": 3, "name": "tv salotto", "ip": "192.168.224.40", "mac": "02:00:5e:00:00:cd"},
    ),
    _modify(
        "dhcp_modify_unchanged",
        {"index": 1},
        notes="nothing changed: every field is sent as the '0' sentinel",
    ),
    _modify(
        "dhcp_modify_refused_duplicate_ip",
        {"index": 1, "ip": "192.168.224.20"},
        refused=True,
    ),
    Scenario(
        name="dhcp_delete",
        page=Page.LAN_SETTINGS,
        endpoint=Endpoint.DHCP_RESERVATION_DELETE,
        call="lan.delete_dhcp_reservation",
        inputs={"index": 2},
        drive=delete_reservation,
    ),
]
