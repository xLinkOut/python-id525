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


LAN_FIELDS = (
    ("ip", "lanHIPAddressText"),
    ("subnet_mask", "lanHSMText"),
    ("dhcp_start", "dhcpstartIPText"),
    ("dhcp_end", "dhcpEndingIPText"),
    ("lease_time", "dhcpLeaseText"),
)


async def save_lan(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    if "dhcp_enabled" in inputs:
        await page.evaluate(
            """([id, on]) => {
                const box = document.getElementById(id);
                box.checked = on;
                box.dispatchEvent(new Event("change", {bubbles: true}));
            }""",
            [f"{pf}-dhcpServer", inputs["dhcp_enabled"]],
        )
    for key, element in LAN_FIELDS:
        if key in inputs:
            await set_value(page, f"{pf}-{element}", str(inputs[key]))
    await click(page, f"{pf}-dhcpBtn")
    if inputs.get("dhcp_enabled") is False:
        await click(page, "confirm_dialog_btn")  # "disable the DHCP server?" dialog


async def set_port_role(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    await click(page, f"{pf}-EthPort_{inputs['role'].upper()}")
    await click(page, f"{pf}-cellularEthPortSaveBtn")


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


def _save(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.LAN_SETTINGS,
        endpoint=Endpoint.LAN_SAVE,
        call="lan.update_settings",
        inputs=inputs,
        call_kwargs={"confirm": True},
        drive=save_lan,
        **kw,
    )


LAN_SCENARIOS = [
    _save(
        "lan_save_dhcp_pool",
        {"dhcp_start": "192.168.224.30", "dhcp_end": "192.168.224.200", "lease_time": 1440},
    ),
    _save(
        "lan_save_new_address",
        {"ip": "192.168.1.1", "dhcp_start": "192.168.1.20", "dhcp_end": "192.168.1.219"},
        notes="address change: the UI does not wait for the answer",
    ),
    _save(
        "lan_save_class_b",
        {
            "ip": "172.16.0.1",
            "subnet_mask": "255.255.0.0",
            "dhcp_start": "172.16.0.20",
            "dhcp_end": "172.16.3.250",
            "lease_time": 2,
        },
    ),
    _save(
        "lan_save_class_a",
        {
            "ip": "10.0.0.1",
            "subnet_mask": "255.0.0.0",
            "dhcp_start": "10.0.0.20",
            "dhcp_end": "10.0.255.250",
            "lease_time": 43200,
        },
    ),
    _save(
        "lan_save_subnet_25",
        {
            "subnet_mask": "255.255.255.128",
            "dhcp_start": "192.168.224.20",
            "dhcp_end": "192.168.224.126",
        },
    ),
    _save(
        "lan_save_dhcp_off",
        {"dhcp_enabled": False, "lease_time": 1},
        notes="DHCP off: the lease time is sent unchecked; the UI asks for confirmation",
    ),
    _save(
        "lan_save_bridge_mode",
        {"ip": "192.168.50.1"},
        fixture="synthetic/lan-settings-bridge",
        synthetic=True,
        notes="bridge mode: the UI moves the DHCP range to .200-.240 of the new subnet",
    ),
    _save("lan_save_refused_unchanged", {}, refused=True, notes="nothing changed"),
    _save("lan_save_refused_bad_ip", {"ip": "192.168.224.300"}, refused=True),
    _save("lan_save_refused_bad_mask", {"subnet_mask": "255.255.255"}, refused=True),
    _save(
        "lan_save_refused_class_c_range",
        {"ip": "224.0.0.1", "dhcp_start": "224.0.0.20", "dhcp_end": "224.0.0.200"},
        refused=True,
    ),
    _save(
        "lan_save_refused_class_b_range",
        {"ip": "192.168.0.1", "subnet_mask": "255.255.0.0"},
        refused=True,
        notes="a 192.x address is class C, so a class B mask is refused",
    ),
    _save(
        "lan_save_refused_loopback",
        {"ip": "127.0.0.1", "subnet_mask": "255.0.0.0"},
        refused=True,
    ),
    _save("lan_save_refused_mask_254", {"subnet_mask": "255.255.255.254"}, refused=True),
    _save(
        "lan_save_refused_class_b_mask",
        {"ip": "172.16.0.1", "subnet_mask": "255.255.0.1"},
        refused=True,
    ),
    _save(
        "lan_save_refused_class_a_mask",
        {"ip": "10.0.0.1", "subnet_mask": "255.0.1.0"},
        refused=True,
    ),
    _save(
        "lan_save_refused_mask_holes",
        {"subnet_mask": "255.255.255.100"},
        refused=True,
        notes="not a contiguous mask",
    ),
    _save(
        "lan_save_refused_network_address",
        {"ip": "192.168.224.0"},
        refused=True,
    ),
    _save(
        "lan_save_refused_bad_start",
        {"dhcp_start": "192.168.224"},
        refused=True,
    ),
    _save(
        "lan_save_refused_bad_end",
        {"dhcp_end": "192.168.224.x"},
        refused=True,
    ),
    _save(
        "lan_save_refused_start_after_end",
        {"dhcp_start": "192.168.224.100", "dhcp_end": "192.168.224.50"},
        refused=True,
    ),
    _save(
        "lan_save_refused_ip_in_pool",
        {"ip": "192.168.224.50"},
        refused=True,
    ),
    _save(
        "lan_save_refused_pool_at_network",
        {"dhcp_start": "192.168.224.0"},
        refused=True,
        notes="the router address .1 falls inside .0-.219, and the range starts at the network",
    ),
    _save(
        "lan_save_refused_pool_at_broadcast",
        {"dhcp_end": "192.168.224.255", "ip": "192.168.224.100"},
        refused=True,
    ),
    _save(
        "lan_save_refused_start_outside",
        {"ip": "192.168.224.250", "dhcp_start": "192.168.223.20"},
        refused=True,
        notes="start below the subnet while the router address is above the range",
    ),
    _save(
        "lan_save_refused_end_outside",
        {"dhcp_end": "192.168.225.20"},
        refused=True,
    ),
    _save("lan_save_refused_lease_short", {"lease_time": 1}, refused=True),
    _save("lan_save_refused_lease_long", {"lease_time": 43201}, refused=True),
]

PORT_SCENARIOS = [
    Scenario(
        name=f"eth_port_{role}",
        page=Page.LAN_SETTINGS,
        endpoint=Endpoint.ETH_WAN,
        call="lan.set_ethernet_port_role",
        inputs={"role": role},
        call_kwargs={"confirm": True},
        drive=set_port_role,
        notes="sent even when unchanged; applied after a reboot",
    )
    for role in ("wan", "lan")
]

SCENARIOS = [
    *LAN_SCENARIOS,
    *PORT_SCENARIOS,
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
    _add(
        "dhcp_add_refused_empty_name",
        {"name": "", "ip": "192.168.224.60", "mac": "02:00:5e:00:00:ac"},
        refused=True,
    ),
    _add(
        "dhcp_add_refused_long_name",
        {"name": "n" * 33, "ip": "192.168.224.60", "mac": "02:00:5e:00:00:ac"},
        refused=True,
    ),
    _add(
        "dhcp_add_refused_bad_ip",
        {"name": "nas", "ip": "192.168.224.256", "mac": "02:00:5e:00:00:ac"},
        refused=True,
    ),
    _add(
        "dhcp_add_refused_duplicate_name",
        {"name": "device01", "ip": "192.168.224.60", "mac": "02:00:5e:00:00:ac"},
        refused=True,
    ),
    _add(
        "dhcp_add_refused_duplicate_ip",
        {"name": "nas", "ip": "192.168.224.92", "mac": "02:00:5e:00:00:ac"},
        refused=True,
    ),
    _modify("dhcp_modify_ip", {"index": 7, "ip": "192.168.224.21"}),
    _modify(
        "dhcp_modify_all",
        {"index": 12, "name": "tv salotto", "ip": "192.168.224.40", "mac": "02:00:5e:00:00:cd"},
    ),
    _modify(
        "dhcp_modify_unchanged",
        {"index": 4},
        notes="nothing changed: every field is sent as the '0' sentinel",
    ),
    _modify(
        "dhcp_modify_refused_duplicate_ip",
        {"index": 4, "ip": "192.168.224.20"},
        refused=True,
    ),
    Scenario(
        name="dhcp_delete",
        page=Page.LAN_SETTINGS,
        endpoint=Endpoint.DHCP_RESERVATION_DELETE,
        call="lan.delete_dhcp_reservation",
        inputs={"index": 7},
        drive=delete_reservation,
    ),
]
