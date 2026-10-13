"""self-tracert.html: traceroute from the router."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix, set_value

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

TRACE = " 1  192.0.2.1  1.1 ms<br> 2  198.51.100.1  9.8 ms<br> 3  203.0.113.5  12.0 ms"


async def traceroute(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    if "host" in inputs:
        await set_value(page, f"{pf}-IPAddressText", inputs["host"])
    await click(page, f"{pf}-TraceTestBtn")


def _trace(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.TRACEROUTE,
        endpoint=Endpoint.TRACEROUTE,
        call="diagnostics.traceroute",
        inputs=inputs,
        drive=traceroute,
        **kw,
    )


SCENARIOS = [
    _trace(
        "traceroute_host",
        {"host": "www.example.com"},
        answers={"req_traceRouteTest": {"trace_result": TRACE, "traceRouteID": 1}},
        notes="traceRouteID counts the runs since the page (client) was created",
    ),
    _trace(
        "traceroute_default_host",
        {},
        answers={"req_traceRouteTest": {"trace_result": TRACE, "traceRouteID": 1}},
        notes="the page's default target (8.8.8.8)",
    ),
    _trace(
        "traceroute_router_fails",
        {"host": "192.0.2.200"},
        answers={"req_traceRouteTest": {"result": False}},
    ),
    _trace("traceroute_refused_empty_host", {"host": ""}, refused=True),
]
