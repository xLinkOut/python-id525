"""fw-portfwd.html: DMZ, port-forwarding switch and rules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix, set_value

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

RULES = "synthetic/fw-portfwd-rules"
_PROTOCOL_ITEM = {"tcp": "tcp", "udp": "udp", "both": "both"}


async def _set_checked(page: BrowserPage, element_id: str, *, checked: bool) -> None:
    await page.evaluate(
        """([id, checked]) => {
            const el = document.getElementById(id);
            el.checked = checked;
            el.dispatchEvent(new Event("change", {bubbles: true}));
        }""",
        [element_id, checked],
    )


async def dmz(page: BrowserPage, inputs: dict[str, Any], *, enabled: bool) -> None:
    pf = await platform_prefix(page)
    await _set_checked(page, f"{pf}-dmz_switch", checked=enabled)
    if "ip" in inputs:
        await set_value(page, f"{pf}-dmz_ip", inputs["ip"])
    await click(page, f"{pf}-dmz_status_applyBtn")


async def enable_dmz(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await dmz(page, inputs, enabled=True)


async def disable_dmz(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await dmz(page, inputs, enabled=False)


async def status(page: BrowserPage, *, enabled: bool) -> None:
    pf = await platform_prefix(page)
    await _set_checked(page, f"{pf}-pf_switch", checked=enabled)
    await click(page, f"{pf}-port_forward_applyBtn")


async def enable(page: BrowserPage, inputs: dict[str, Any]) -> None:
    del inputs
    await status(page, enabled=True)


async def disable(page: BrowserPage, inputs: dict[str, Any]) -> None:
    del inputs
    await status(page, enabled=False)


async def add_rule(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"{await platform_prefix(page)}-addNewBtn")
    await click(page, f"ProtocolSelect_{inputs.get('protocol', 'both')}")
    if inputs.get("wan_port_end"):
        await click(page, "PortTypeSelect_range")
        await set_value(page, "PortEnd", str(inputs["wan_port_end"]))
    await set_value(page, "PortBegin", str(inputs["wan_port"]))
    await set_value(page, "lanipAddr", inputs["lan_ip"])
    await set_value(page, "LANPortBegin", str(inputs["lan_port"]))
    await _set_checked(page, "StatusCheckBox", checked=inputs.get("enabled", True))
    await click(page, "add_pf_btn")


async def edit_rule(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"edit_rule_{inputs['instance']}")
    if "protocol" in inputs:
        await click(page, f"edit_ProtocolSelect_{inputs['protocol']}")
    if "wan_port_end" in inputs:
        if inputs["wan_port_end"]:
            await click(page, "edit_PortTypeSelect_range")
            await set_value(page, "edit_PortEnd", str(inputs["wan_port_end"]))
        else:
            await click(page, "edit_PortTypeSelect_single")
    if "wan_port" in inputs:
        await set_value(page, "edit_PortBegin", str(inputs["wan_port"]))
    if "lan_ip" in inputs:
        await set_value(page, "edit_lanipAddr", inputs["lan_ip"])
    if "lan_port" in inputs:
        await set_value(page, "edit_LANPortBegin", str(inputs["lan_port"]))
    if "enabled" in inputs:
        await _set_checked(page, "edit_StatusCheckBox", checked=inputs["enabled"])
    await click(page, "edit_rule_save_btn")


async def delete_rule(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"deleteItem_{inputs['instance']}")
    await click(page, "confirm_delete_btn")


def _s(
    name: str,
    endpoint: Endpoint,
    call: str,
    inputs: dict[str, Any],
    drive: Any,
    *,
    synthetic: bool = False,
    **kw: Any,
) -> Scenario:
    return Scenario(
        name=name,
        page=Page.PORT_FORWARDING,
        endpoint=endpoint,
        call=f"port_forwarding.{call}",
        inputs=inputs,
        drive=drive,
        fixture=RULES if synthetic else None,
        synthetic=synthetic,
        **kw,
    )


_DMZ, _STATUS = Endpoint.DMZ_SAVE, Endpoint.PORTFWD_STATUS
_ADD, _EDIT, _DEL = Endpoint.PORTFWD_ADD, Endpoint.PORTFWD_EDIT, Endpoint.PORTFWD_DELETE
_NEW = {"lan_ip": "192.168.224.70", "lan_port": 443}

SCENARIOS = [
    _s("dmz_enable", _DMZ, "enable_dmz", {"ip": "192.168.224.77"}, enable_dmz),
    _s(
        "dmz_enable_lenient_octets",
        _DMZ,
        "enable_dmz",
        {"ip": "10.1.2.03"},
        enable_dmz,
        notes="octets are only checked with parseInt (1..254): any subnet, leading zeros",
    ),
    _s(
        "dmz_disable",
        _DMZ,
        "disable_dmz",
        {},
        disable_dmz,
        notes="the current (empty) DMZ address is sent back",
    ),
    _s(
        "dmz_refused_router_ip",
        _DMZ,
        "enable_dmz",
        {"ip": "192.168.224.1"},
        enable_dmz,
        refused=True,
    ),
    _s(
        "dmz_refused_broadcast",
        _DMZ,
        "enable_dmz",
        {"ip": "192.168.224.255"},
        enable_dmz,
        refused=True,
    ),
    _s(
        "dmz_refused_three_octets",
        _DMZ,
        "enable_dmz",
        {"ip": "192.168.224"},
        enable_dmz,
        refused=True,
    ),
    _s("portfwd_enable", _STATUS, "enable", {}, enable),
    _s("portfwd_disable", _STATUS, "disable", {}, disable, synthetic=True),
    _s(
        "portfwd_add_tcp",
        _ADD,
        "add_rule",
        {"wan_port": 8443, **_NEW, "protocol": "tcp"},
        add_rule,
    ),
    _s(
        "portfwd_add_range_disabled",
        _ADD,
        "add_rule",
        {
            "wan_port": 6000,
            "wan_port_end": 6005,
            "lan_ip": "192.168.224.71",
            "lan_port": 6000,
            "protocol": "both",
            "enabled": False,
        },
        add_rule,
    ),
    _s(
        "portfwd_add_udp_cidr_address",
        _ADD,
        "add_rule",
        {"wan_port": 51820, "lan_ip": "192.168.224.72/24", "lan_port": 51820, "protocol": "udp"},
        add_rule,
        notes="UI quirk: the address check accepts a /prefix and sends it as typed",
    ),
    _s(
        "portfwd_add_refused_port_zero",
        _ADD,
        "add_rule",
        {"wan_port": 0, **_NEW},
        add_rule,
        refused=True,
    ),
    _s(
        "portfwd_add_refused_port_too_big",
        _ADD,
        "add_rule",
        {"wan_port": 65536, **_NEW},
        add_rule,
        refused=True,
    ),
    _s(
        "portfwd_add_refused_range_reversed",
        _ADD,
        "add_rule",
        {"wan_port": 7000, "wan_port_end": 7000, **_NEW},
        add_rule,
        refused=True,
    ),
    _s(
        "portfwd_add_refused_lan_port",
        _ADD,
        "add_rule",
        {"wan_port": 7000, "lan_ip": "192.168.224.70", "lan_port": 70000},
        add_rule,
        refused=True,
    ),
    _s(
        "portfwd_add_refused_empty_ip",
        _ADD,
        "add_rule",
        {"wan_port": 7000, "lan_ip": "", "lan_port": 22},
        add_rule,
        refused=True,
    ),
    _s(
        "portfwd_add_refused_other_network",
        _ADD,
        "add_rule",
        {"wan_port": 7000, "lan_ip": "10.0.0.5", "lan_port": 22},
        add_rule,
        refused=True,
    ),
    _s(
        "portfwd_add_refused_bad_ip",
        _ADD,
        "add_rule",
        {"wan_port": 7000, "lan_ip": "192.168.224", "lan_port": 22},
        add_rule,
        refused=True,
    ),
    _s(
        "portfwd_add_refused_broadcast",
        _ADD,
        "add_rule",
        {"wan_port": 7000, "lan_ip": "192.168.224.255", "lan_port": 22},
        add_rule,
        refused=True,
    ),
    _s(
        "portfwd_add_refused_router_ip",
        _ADD,
        "add_rule",
        {"wan_port": 7000, "lan_ip": "192.168.224.1", "lan_port": 22},
        add_rule,
        refused=True,
    ),
    _s(
        "portfwd_edit_wan_port",
        _EDIT,
        "modify_rule",
        {"instance": 3, "wan_port": 8081},
        edit_rule,
        synthetic=True,
        notes="every field is resent, unchanged ones from the rule",
    ),
    _s(
        "portfwd_edit_range",
        _EDIT,
        "modify_rule",
        {"instance": 5, "protocol": "udp", "wan_port_end": 5020, "enabled": True},
        edit_rule,
        synthetic=True,
    ),
    _s(
        "portfwd_edit_range_to_single",
        _EDIT,
        "modify_rule",
        {"instance": 5, "wan_port_end": 0, "lan_ip": "192.168.224.61", "lan_port": 5001},
        edit_rule,
        synthetic=True,
    ),
    _s(
        "portfwd_edit_refused_lan_port",
        _EDIT,
        "modify_rule",
        {"instance": 3, "lan_port": 70000},
        edit_rule,
        synthetic=True,
        refused=True,
    ),
    _s("portfwd_delete", _DEL, "delete_rule", {"instance": 5}, delete_rule, synthetic=True),
]
