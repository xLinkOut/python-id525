from __future__ import annotations

import pytest

from id525 import Id525ValidationError
from id525.sections.lan import parse_lan_page

from .conftest import ClientFactory, FakeRouter, load_fixture


def test_parse_lan_page() -> None:
    lan = parse_lan_page(load_fixture("lan-settings.html"))
    assert lan.ip == "192.168.224.1"
    assert lan.subnet_mask == "255.255.255.0"
    assert lan.dhcp_enabled is True
    assert (lan.dhcp_start, lan.dhcp_end) == ("192.168.224.20", "192.168.224.219")
    assert lan.lease_time == 720
    assert lan.operation_mode == "Router"
    assert [r.index for r in lan.reservations] == [1, 2, 3]
    first = lan.reservations[0]
    assert (first.name, first.mac, first.ip) == ("device01", "02:00:5e:00:00:01", "192.168.224.92")
    assert first.active is True
    assert first.interface_index == 1


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
