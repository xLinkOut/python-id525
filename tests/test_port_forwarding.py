from __future__ import annotations

import json

import pytest

from id525 import Id525ValidationError
from id525.sections.port_forwarding import (
    PortForwardProtocol,
    _js_int,
    parse_port_forwarding_page,
)

from .conftest import FIXTURES, ClientFactory, FakeRouter, load_fixture

RULES = "synthetic/fw-portfwd-rules"


def test_parse_real_page() -> None:
    settings = parse_port_forwarding_page(load_fixture("fw-portfwd.html"))
    assert settings.enabled is False
    assert settings.dmz_enabled is False
    assert settings.dmz_ip is None
    assert settings.rules == ()
    assert settings.router_ip == "192.168.224.1"
    assert settings.raw["ip_class_index"] == 1


def test_parse_rules() -> None:
    settings = parse_port_forwarding_page(load_fixture(f"{RULES}.html"))
    assert settings.enabled is True
    single, ranged = settings.rules
    assert (single.instance, single.wan_port, single.wan_port_end, single.lan_port) == (
        3,
        8080,
        0,
        80,
    )
    assert single.protocol is PortForwardProtocol.TCP
    assert single.enabled is True
    assert single.description is None  # "---"
    assert (ranged.wan_port, ranged.wan_port_end, ranged.protocol) == (
        5000,
        5010,
        PortForwardProtocol.BOTH,
    )
    assert ranged.enabled is False


@pytest.mark.parametrize(
    ("raw", "protocol"),
    [(0, "tcp"), (1, "udp"), (2, "both"), ("1", "udp"), (7, "tcp"), (None, "tcp")],
)
def test_protocol_from_wire(raw: object, protocol: str) -> None:
    assert PortForwardProtocol.from_wire(raw) == protocol


@pytest.mark.parametrize(
    ("text", "value"),
    [("12", 12), ("012", 12), (" 7x", 7), ("5/24", 5), ("", None), ("x1", None), ("-3", -3)],
)
def test_js_int_matches_parse_int(text: str, value: int | None) -> None:
    assert _js_int(text) == value


async def test_add_refused_at_ten_rules(make_client: ClientFactory, router: FakeRouter) -> None:
    rules = [
        {
            "instance": i,
            "description": "---",
            "internalClient": f"192.168.224.{100 + i}",
            "externalPort": 1000 + i,
            "externalPortEndRange": 0,
            "internalPort": 1000 + i,
            "protocol": 0,
            "enable": 1,
        }
        for i in range(10)
    ]
    encoded = json.dumps(rules).replace('"', "&quot;")
    html = load_fixture("fw-portfwd.html").replace(
        'var port_fwd_entries = "[]";', f'var port_fwd_entries = "{encoded}";'
    )
    path = FIXTURES / "synthetic" / "_test-portfwd-full.html"
    path.write_text(html)
    try:
        router.page_fixtures["fw-portfwd"] = "synthetic/_test-portfwd-full"
        client = await make_client(read_only=False)
        with pytest.raises(Id525ValidationError, match="at most 10"):
            await client.port_forwarding.add_rule(9000, "192.168.224.80", 9000)
    finally:
        path.unlink()
    assert "portforward_add" not in router.calls


async def test_enable_dmz_defaults_to_current_host(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match="invalid DMZ host"):
        await client.port_forwarding.enable_dmz()  # the page has no DMZ host yet
    assert "dmz_save" not in router.calls


@pytest.mark.parametrize("call", ["modify_rule", "delete_rule"])
async def test_unknown_instance(call: str, make_client: ClientFactory, router: FakeRouter) -> None:
    router.page_fixtures["fw-portfwd"] = RULES
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match="no port-forwarding rule"):
        await getattr(client.port_forwarding, call)(99)


async def test_status_needs_no_page(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client(read_only=False)
    await client.port_forwarding.enable()
    assert not [c for c in router.calls if c.startswith("page:")]
    assert json.loads(dict(router.bodies)["set_portforward_status"])["isPFEnable"] == "1"
