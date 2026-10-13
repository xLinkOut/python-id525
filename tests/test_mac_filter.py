from __future__ import annotations

import json

import pytest

from id525 import Id525ValidationError
from id525.sections.mac_filter import MacFilterMode, parse_mac_filter_page

from .conftest import FIXTURES, ClientFactory, FakeRouter, load_fixture

RULES = "synthetic/fw-macfilter-rules"


def test_parse_real_page() -> None:
    settings = parse_mac_filter_page(load_fixture("fw-macfilter.html"))
    assert settings.enabled is False
    assert settings.mode is MacFilterMode.BLACKLIST
    assert settings.rules == ()
    assert len(settings.clients) == 6
    assert settings.clients[1].mac == "02:00:5e:00:00:04"
    assert settings.clients[4].hostname is None  # "N\/A"


def test_parse_rules() -> None:
    settings = parse_mac_filter_page(load_fixture(f"{RULES}.html"))
    assert [(r.instance, r.name, r.mac) for r in settings.rules] == [
        (2, "tablet", "02:00:5E:00:01:0A"),
        (6, "console-1", "02:00:5E:00:00:06"),
    ]


def test_mode_wire_values() -> None:
    assert MacFilterMode.WHITELIST.wire == "1"
    assert MacFilterMode.BLACKLIST.wire == "0"


async def test_get_settings(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    settings = await client.mac_filter.get_settings()
    assert len(settings.clients) == 6
    assert router.count("page:fw-macfilter") == 1


async def test_add_refused_at_ten_rules(make_client: ClientFactory, router: FakeRouter) -> None:
    rules = [
        {"instance": i, "description": f"d{i}", "macAddress": f"02:00:5e:00:03:{i:02x}"}
        for i in range(10)
    ]
    encoded = json.dumps(rules).replace('"', "&quot;")
    html = load_fixture("fw-macfilter.html").replace('var tmp = "[]";', f'var tmp = "{encoded}";')
    path = FIXTURES / "synthetic" / "_test-macfilter-full.html"
    path.write_text(html)
    try:
        router.page_fixtures["fw-macfilter"] = "synthetic/_test-macfilter-full"
        client = await make_client(read_only=False)
        with pytest.raises(Id525ValidationError, match="at most 10"):
            await client.mac_filter.add_rule("02:00:5e:00:04:01", "nas")
        # the connected-client button is not limited by the UI
        await client.mac_filter.add_connected_client("02:00:5E:00:00:04")
    finally:
        path.unlink()
    assert router.count("macfilter_add") == 1


async def test_add_connected_client_must_be_connected(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match="not a connected client"):
        await client.mac_filter.add_connected_client("02:00:5e:00:09:09")
    assert "macfilter_add" not in router.calls


async def test_add_connected_client_sends_the_listed_spelling(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(read_only=False)
    await client.mac_filter.add_connected_client("02:00:5E:00:00:04")
    body = json.loads(dict(router.bodies)["macfilter_add"])
    assert body["clientMac"] == "02:00:5e:00:00:04"


@pytest.mark.parametrize("call", ["modify_rule", "delete_rule"])
async def test_unknown_instance(call: str, make_client: ClientFactory, router: FakeRouter) -> None:
    router.page_fixtures["fw-macfilter"] = RULES
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match="no MAC filter rule"):
        await getattr(client.mac_filter, call)(99)
