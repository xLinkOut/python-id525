from __future__ import annotations

import pytest

from id525 import Id525ValidationError
from id525.sections.ip_filter import FilterMode
from id525.sections.url_filter import parse_rules, parse_url_filter_page

from .conftest import ClientFactory, FakeRouter, load_fixture


def test_parse_real_page_with_garbage_profile() -> None:
    settings = parse_url_filter_page(load_fixture("fw-urlfilter.html"))
    assert settings.enabled is False
    assert settings.mode is FilterMode.BLACKLIST
    assert settings.rules == ()


def test_parse_synthetic_rules() -> None:
    settings = parse_url_filter_page(load_fixture("synthetic/fw-urlfilter-rules.html"))
    assert settings.enabled is True
    assert settings.mode is FilterMode.WHITELIST
    assert [(r.instance, r.url) for r in settings.rules] == [
        ("3", "example.com"),
        ("5", "ads.example.net"),
        ("9", "http://tracker.example.org/x~y#z"),
    ]


@pytest.mark.parametrize(
    ("profile", "expected"),
    [("", 0), ("1,a.com", 0), ("1,a.com;", 1), ("1,a.com;2,b.com;", 2), ("7;", 1)],
)
def test_parse_rules_like_the_ui(profile: str, expected: int) -> None:
    assert len(parse_rules(profile)) == expected


async def test_add_refuses_an_eleventh_url(
    make_client: ClientFactory, router: FakeRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = "".join(f"{i},site{i}.example.com;" for i in range(10))
    html = load_fixture("synthetic/fw-urlfilter-rules.html").replace(
        "3,example.com;5,ads.example.net;9,http://tracker.example.org/x~y#z;", profile
    )
    monkeypatch.setattr("tests.conftest.load_fixture", lambda name: html)
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match="at most 10"):
        await client.url_filter.add_url("new.example.com")
    assert "urlfilter_add_save" not in router.calls


async def test_unknown_instance(make_client: ClientFactory) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match="no URL filter rule"):
        await client.url_filter.delete_url("1")
