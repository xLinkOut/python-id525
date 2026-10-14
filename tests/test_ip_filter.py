from __future__ import annotations

import pytest

from id525 import Id525ValidationError
from id525.sections.ip_filter import FilterMode, parse_ip_filter_page

from .conftest import ClientFactory, FakeRouter, load_fixture


def test_parse_real_page_has_no_rules() -> None:
    settings = parse_ip_filter_page(load_fixture("fw-ipfilter.html"))
    assert settings.enabled is False
    assert settings.mode is FilterMode.BLACKLIST
    assert settings.rules == ()


def test_parse_synthetic_rules() -> None:
    settings = parse_ip_filter_page(load_fixture("synthetic/fw-ipfilter-rules.html"))
    assert settings.enabled is True
    assert settings.mode is FilterMode.WHITELIST
    assert [(r.instance, r.ip, r.ip_type) for r in settings.rules] == [
        (3, "192.0.2.10", "IPv4"),
        (8, "2001:db8::5", "IPv6"),
        (11, "198.51.100.7", "IPv4"),
    ]


def _with_rules(count: int) -> str:
    rules = ",".join(
        f"{{&quot;instance&quot;:{i},&quot;dst_ip&quot;:&quot;192.0.2.{i}&quot;,"
        f"&quot;protocol&quot;:&quot;TCP/UDP&quot;,&quot;ip_type&quot;:&quot;IPv4&quot;}}"
        for i in range(1, count + 1)
    )
    return load_fixture("fw-ipfilter.html").replace(
        'var ipFilter_entries = "[]";', f'var ipFilter_entries = "[{rules}]";'
    )


async def test_add_refuses_an_eleventh_rule(
    make_client: ClientFactory, router: FakeRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = _with_rules(10)
    monkeypatch.setattr("tests.conftest.load_fixture", lambda name: html)
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match="at most 10"):
        await client.ip_filter.add_rule("203.0.113.1")
    assert "ipfilter_add" not in router.calls


async def test_unknown_instance(make_client: ClientFactory) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match="no IP filter rule"):
        await client.ip_filter.edit_rule("42", "203.0.113.1")
    with pytest.raises(Id525ValidationError, match="no IP filter rule"):
        await client.ip_filter.delete_rule("42")
