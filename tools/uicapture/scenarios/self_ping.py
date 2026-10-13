"""self-ping.html: ping from the router."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix, set_value

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

FIELDS = (("host", "IPAddressText"), ("count", "CountText"), ("size", "PacketSizeText"))


async def ping(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    for key, element in FIELDS:
        if key in inputs:
            await set_value(page, f"{pf}-{element}", str(inputs[key]))
    await click(page, f"{pf}-PingTestBtn")


def _echo(seq: int) -> dict[str, Any]:
    return {"ping_result": f"64 bytes from 192.0.2.7: icmp_seq={seq} ttl=56 time=1{seq}.2 ms"}


def _ping(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.PING,
        endpoint=Endpoint.PING,
        call="diagnostics.ping",
        inputs=inputs,
        call_kwargs={"interval": 0},
        drive=ping,
        **kw,
    )


SCENARIOS = [
    _ping(
        "ping_host",
        {"host": "www.example.com", "count": 2, "size": 56},
        answers={"req_pingTest": [_echo(1), _echo(2), _echo(3)]},
        notes="count + 1 requests; the answer to the last one is discarded by the UI",
    ),
    _ping(
        "ping_odd_host",
        {"host": 'host a&b%"ü', "count": 1, "size": 8},
        answers={"req_pingTest": [_echo(1), _echo(2)]},
        notes="the UI does not validate the host: it is sent as typed",
    ),
    _ping(
        "ping_defaults",
        {},
        answers={"req_pingTest": [_echo(i) for i in range(1, 12)]},
        notes="the page's defaults: router LAN IP, 10 echoes, 32 bytes",
    ),
    _ping(
        "ping_router_fails",
        {"host": "192.0.2.99", "count": 3, "size": 32},
        answers={"req_pingTest": [_echo(1), {"result": False}]},
        notes="result false stops the loop",
    ),
    _ping("ping_refused_empty_host", {"host": "", "count": 2, "size": 32}, refused=True),
    _ping("ping_refused_zero_size", {"host": "192.0.2.7", "count": 2, "size": 0}, refused=True),
    _ping("ping_refused_zero_count", {"host": "192.0.2.7", "count": 0, "size": 32}, refused=True),
    _ping(
        "ping_refused_negative_count", {"host": "192.0.2.7", "count": -1, "size": 32}, refused=True
    ),
]
