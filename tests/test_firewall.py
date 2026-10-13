from __future__ import annotations

import pytest

from id525.sections.firewall import FirewallLevel, parse_firewall_page

from .conftest import ClientFactory, FakeRouter, load_fixture


def test_parse_firewall_page() -> None:
    settings = parse_firewall_page(load_fixture("fw-adv.html"))
    assert settings.level is FirewallLevel.MIDDLE
    assert settings.vpn_passthrough is True


@pytest.mark.parametrize(("value", "level"), [("1", "low"), ("3", "high"), ("7", "middle")])
def test_parse_level(value: str, level: str) -> None:
    html = load_fixture("fw-adv.html").replace(
        "var level_apply = 2;", f"var level_apply = {value};"
    )
    assert parse_firewall_page(html).level == level


def test_parse_vpn_off() -> None:
    html = load_fixture("fw-adv.html").replace('var vpn_status ="1";', 'var vpn_status ="0";')
    assert parse_firewall_page(html).vpn_passthrough is False


async def test_get_settings(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    assert (await client.firewall.get_settings()).level is FirewallLevel.MIDDLE
    assert router.count("page:fw-adv") == 1


async def test_set_level_rejects_unknown(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(ValueError, match="extreme"):
        await client.firewall.set_level("extreme")  # type: ignore[arg-type]
    assert "fw_adv_apply" not in router.calls
