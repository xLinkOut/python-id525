from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from id525 import Id525CommandError, Id525ValidationError
from id525.sections.lan import EthernetPortRole, network_range, parse_lan_page

from .conftest import ClientFactory, FakeRouter, load_fixture

GOLDEN = Path(__file__).parent / "golden"


def test_parse_lan_page() -> None:
    lan = parse_lan_page(load_fixture("lan-settings.html"))
    assert lan.ip == "192.168.224.1"
    assert lan.subnet_mask == "255.255.255.0"
    assert lan.dhcp_enabled is True
    assert (lan.dhcp_start, lan.dhcp_end) == ("192.168.224.20", "192.168.224.219")
    assert lan.lease_time == 720
    assert lan.operation_mode == "Router"
    assert [r.index for r in lan.reservations] == [4, 7, 12]
    first = lan.reservations[0]
    assert (first.name, first.mac, first.ip) == ("device01", "02:00:5e:00:00:01", "192.168.224.92")
    assert first.active is True
    assert first.interface_index == 2


async def test_get_settings(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    lan = await client.lan.get_settings()
    assert len(lan.reservations) == 3
    assert router.count("page:lan-settings") == 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"name": "", "ip": "192.168.224.60", "mac": "02:00:5e:00:00:aa"}, "empty"),
        ({"name": "x" * 33, "ip": "192.168.224.60", "mac": "02:00:5e:00:00:aa"}, "longer"),
        ({"name": "nas", "ip": "192.168.224.256", "mac": "02:00:5e:00:00:aa"}, "invalid IP"),
        ({"name": "device01", "ip": "192.168.224.60", "mac": "02:00:5e:00:00:aa"}, "named"),
        ({"name": "nas", "ip": "192.168.224.92", "mac": "02:00:5e:00:00:aa"}, "reserved"),
    ],
)
async def test_add_validation(
    kwargs: dict[str, str], message: str, make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match=message):
        await client.lan.add_dhcp_reservation(**kwargs)
    assert "req_LanStaticAddrAdd" not in router.calls


async def test_unknown_reservation_index(make_client: ClientFactory) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match="no DHCP reservation"):
        await client.lan.delete_dhcp_reservation(99)


def test_parse_port_role_and_mode() -> None:
    lan = parse_lan_page(load_fixture("lan-settings.html"))
    assert lan.ethernet_port_role is EthernetPortRole.LAN
    assert lan.ethernet_port == 2
    bridge = parse_lan_page(load_fixture("synthetic/lan-settings-bridge.html"))
    assert bridge.operation_mode == "Bridge"


def test_reservation_names_are_uri_decoded() -> None:
    html = load_fixture("lan-settings.html").replace("device01", "living%20room")
    assert parse_lan_page(html).reservations[0].name == "living room"


@pytest.mark.parametrize(
    ("ip", "mask", "ip_class", "expected"),
    [
        ("192.168.224.1", "255.255.255.0", 0, ("192.168.224.0", "192.168.224.255")),
        ("192.168.224.200", "255.255.255.128", 0, ("192.168.224.128", "192.168.224.255")),
        ("172.16.5.1", "255.255.252.0", 1, ("172.16.4.0", "172.16.7.255")),
        ("10.70.0.1", "255.192.0.0", 2, ("10.64.0.0", "10.127.255.255")),
        ("192.168.224.1", "255.255.255.100", 0, None),
    ],
)
def test_network_range(ip: str, mask: str, ip_class: int, expected: tuple[str, str] | None) -> None:
    assert network_range(ip, mask, ip_class) == expected


UI_MESSAGE_TO_CLIENT = {
    "LAN mode change failed.": "invalid",
    "No Internet protocol configurations changed.": "nothing to change",
    "Please input valid host IP address.": "class",
    "Please input valid subnet mask address.": "subnet mask must be",
    "Please input valid starting IP Address.": "start address",
    "Please input valid ending IP Address.": "end address",
    "Please input valid IP address range.": "after the end",
    "DHCP pool range can not include host IP.": "inside the DHCP range",
    "Starting IP can not equal network IP.": "network address",
    "Ending IP can not equal brosdcast IP.": "broadcast address",
    "Lease time is invalid.": "lease time",
}


LAN_REFUSALS = [
    json.loads(path.read_text()) for path in sorted(GOLDEN.glob("lan_save_refused_*.json"))
]


@pytest.mark.parametrize("golden", LAN_REFUSALS, ids=lambda g: g["scenario"])
async def test_lan_refusals_have_the_ui_reason(
    golden: dict[str, Any], make_client: ClientFactory
) -> None:
    ui = golden["ui_message"]
    expected = next(v for k, v in UI_MESSAGE_TO_CLIENT.items() if ui.startswith(k))
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match=expected):
        await client.lan.update_settings(**golden["inputs"], confirm=True)


async def test_update_settings_forgets_the_session(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(read_only=False)
    await client.lan.update_settings(lease_time=60, confirm=True)
    assert router.count("req_LanInternetProtoSave") == 1
    assert not client.is_logged_in


async def test_update_settings_tolerates_the_lan_restart(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    router.drop.add("req_LanInternetProtoSave")
    client = await make_client(read_only=False)
    await client.lan.update_settings(
        ip="192.168.1.1", dhcp_start="192.168.1.20", dhcp_end="192.168.1.219", confirm=True
    )
    assert not client.is_logged_in


async def test_update_settings_rejected_keeps_the_session(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    router.answers["req_LanInternetProtoSave"] = {"result": False}
    client = await make_client(read_only=False)
    with pytest.raises(Id525CommandError):
        await client.lan.update_settings(lease_time=60, confirm=True)
    assert client.is_logged_in


async def test_port_role(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client(read_only=False)
    await client.lan.set_ethernet_port_role(EthernetPortRole.WAN, confirm=True)
    assert client.is_logged_in  # applied after a reboot: the session survives
    router.drop.add("req_ethWanEnabled")
    await client.lan.set_ethernet_port_role(EthernetPortRole.LAN, confirm=True)
    assert not client.is_logged_in
    router.drop.clear()
    router.answers["req_ethWanEnabled"] = {"result": False}
    with pytest.raises(Id525CommandError):
        await client.lan.set_ethernet_port_role(EthernetPortRole.LAN, confirm=True)
