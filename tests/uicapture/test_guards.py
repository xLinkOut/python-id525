"""The capture browser must be unable to reach anything but the local mock.

Layers are tested one at a time against targets that are safe to dial:

* a *sentinel* server on 127.0.0.2 (loopback, so reachable if a guard failed,
  and it counts every hit) proves the routing layer;
* TEST-NET-1 192.0.2.1 (RFC 5737, never routed) proves the dead-proxy layer:
  with routing disabled the request must fail fast with a proxy error instead
  of timing out.

The router's own address is never dialled; it only appears in pure-function tests.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from aiohttp import web

from tools.uicapture.browser import guarded_context
from tools.uicapture.guard import GuardLog, install_guards, is_loopback_url
from tools.uicapture.mockrouter import MockRouter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.browser

SENTINEL_HOST = "127.0.0.2"


@pytest.mark.parametrize(
    ("url", "loopback"),
    [
        ("https://192.168.224.1/cgi-bin/cgi/reboot.cgi", False),
        ("http://192.168.224.1:80/", False),
        ("http://192.0.2.1/", False),
        ("https://example.com/", False),
        ("http://[::ffff:c0a8:e001]/", False),  # 192.168.224.1 as IPv4-mapped IPv6
        ("http://127.0.0.1:8080/x", True),
        ("http://localhost/", True),
        ("http://[::1]:1/", True),
    ],
)
def test_url_classification(url: str, loopback: bool) -> None:
    assert is_loopback_url(url) is loopback


def test_mock_refuses_non_loopback_bind(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        MockRouter(pages_dir=tmp_path, assets_dir=None, host="192.168.224.10")
    with pytest.raises(ValueError, match="loopback"):
        MockRouter(pages_dir=tmp_path, assets_dir=None, host="0.0.0.0")


async def test_guards_refuse_a_non_loopback_allowed_origin() -> None:
    with pytest.raises(ValueError, match="non-loopback"):
        await install_guards(None, "https://192.168.224.1", GuardLog())  # type: ignore[arg-type]


@pytest.fixture
async def sentinel() -> AsyncIterator[tuple[str, list[str]]]:
    hits: list[str] = []

    async def record(request: web.Request) -> web.Response:
        hits.append(f"{request.method} {request.path}")
        return web.Response(text="sentinel")

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", record)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, SENTINEL_HOST, 0)
    await site.start()
    port = runner.addresses[0][1]
    yield f"http://{SENTINEL_HOST}:{port}", hits
    await runner.cleanup()


@pytest.fixture
async def mock(tmp_path: Path) -> AsyncIterator[MockRouter]:
    router = MockRouter(pages_dir=tmp_path, assets_dir=None)
    await router.start()
    yield router
    await router.stop()


LEAK_KINDS = {
    "/css",
    "/script.js",
    "/img",
    "/iframe",
    "/form",
    "/fetch",
    "/no-cors",
    "/xhr",
    "/beacon",
    "/ws",
    "/sse",
    "/worker",
    "/popup",
    "/navigate",
}


def leaky_page(target: str) -> str:
    """A page that tries every way a browser has to reach ``target``."""
    ws_target = target.replace("http://", "ws://")
    return f"""<!doctype html><html><head>
<link rel="stylesheet" href="{target}/css">
<link rel="prefetch" href="{target}/prefetch">
<script src="{target}/script.js"></script>
</head><body>
<img src="{target}/img">
<iframe src="{target}/iframe"></iframe>
<form id="f" method="post" action="{target}/form" target="sink"><input name="a" value="b"></form>
<iframe name="sink"></iframe>
<script>
  fetch("{target}/fetch", {{method: "POST", body: "{{}}"}}).catch(() => {{}});
  fetch("{target}/no-cors", {{mode: "no-cors"}}).catch(() => {{}});
  const x = new XMLHttpRequest(); x.open("GET", "{target}/xhr"); x.send();
  navigator.sendBeacon("{target}/beacon", "x");
  try {{ new WebSocket("{ws_target}/ws"); }} catch (e) {{}}
  new EventSource("{target}/sse");
  const w = new Worker(URL.createObjectURL(new Blob(
    ['fetch("{target}/worker").catch(() => {{}})'], {{type: "text/javascript"}})));
  window.open("{target}/popup");
  document.getElementById("f").submit();
  setTimeout(() => {{ window.location = "{target}/navigate"; }}, 300);
</script></body></html>"""


async def test_routing_layer_blocks_every_request_kind(
    mock: MockRouter, sentinel: tuple[str, list[str]]
) -> None:
    target, hits = sentinel
    (mock.pages_dir / "leaky.html").write_text(leaky_page(target))
    async with guarded_context(mock.origin) as (context, log):
        page = await context.new_page()
        await page.goto("/cgi-bin/cm/leaky.html")
        await asyncio.sleep(2)
    assert hits == []  # the sentinel was reachable, yet nothing arrived
    blocked_paths = {url.removeprefix(target) for url in log.blocked}
    assert LEAK_KINDS - {"/ws"} <= blocked_paths, LEAK_KINDS - {"/ws"} - blocked_paths
    assert log.blocked_websockets == [f"{target.replace('http://', 'ws://')}/ws"]


async def test_control_leaky_page_does_reach_the_sentinel_without_routing(
    mock: MockRouter, sentinel: tuple[str, list[str]]
) -> None:
    """Control for the test above: without routing every attempt really fires.

    127.0.0.2 is loopback, so neither the proxy nor the resolver layer applies:
    this proves the leaky page is a meaningful probe and the sentinel is reachable.
    """
    target, hits = sentinel
    (mock.pages_dir / "leaky.html").write_text(leaky_page(target))
    async with guarded_context(mock.origin, routing=False) as (context, _):
        page = await context.new_page()
        await page.goto("/cgi-bin/cm/leaky.html")
        await asyncio.sleep(2)
    reached = {hit.split(" ", 1)[1] for hit in hits}
    assert reached >= LEAK_KINDS, LEAK_KINDS - reached


async def test_proxy_layer_holds_without_routing(mock: MockRouter) -> None:
    async with guarded_context(mock.origin, routing=False) as (context, _):
        page = await context.new_page()
        failures: list[str] = []
        page.on("requestfailed", lambda r: failures.append(r.failure or ""))
        await page.goto("/cgi-bin/cm/blank.html")
        started = time.monotonic()
        error = await page.evaluate(
            "fetch('http://192.0.2.1/').then(() => 'reached', e => String(e))"
        )
        elapsed = time.monotonic() - started
    assert error != "reached"
    assert elapsed < 5  # an unrouted TEST-NET address would hang instead
    assert any("PROXY" in f for f in failures), failures


async def test_mock_is_reachable_through_the_guards(mock: MockRouter) -> None:
    async with guarded_context(mock.origin) as (context, log):
        page = await context.new_page()
        await page.goto("/cgi-bin/cm/blank.html")
        answer = await page.evaluate(
            "fetch('/cgi-bin/cgi/token_query.cgi', {method: 'POST', body: '\"{}\"'})"
            ".then(r => r.json())"
        )
    assert answer["RequestVerifyToken"].startswith("capture-token-")
    assert [r.endpoint for r in mock.requests] == ["token_query"]
    assert log.blocked == []
