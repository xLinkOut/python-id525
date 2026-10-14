"""Network guards for the capture browser: only the local mock is reachable.

Three independent layers, each sufficient on its own for non-loopback targets:

1. **Routing** (context level, so popups, iframes and navigations are covered):
   every request whose origin is not exactly the mock's origin is aborted, and
   so is every WebSocket. Service workers are blocked so they cannot bypass it.
2. **Dead proxy**: Chromium sends every non-loopback request to a proxy on
   127.0.0.1:9 (discard port, nothing listens), so even a request that escaped
   routing fails at connect time.
3. **No name resolution**: the host resolver maps every name except
   ``localhost`` and ``127.*`` to "not found".

Plus: the mock binds to 127.0.0.1 only and refuses anything else.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Route, WebSocketRoute

DEAD_PROXY = "http://127.0.0.1:9"

LAUNCH_ARGS: tuple[str, ...] = (
    f"--proxy-server={DEAD_PROXY}",  # loopback is implicitly bypassed by Chromium
    "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.*",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-sync",
    "--dns-prefetch-disable",
    "--no-pings",
    "--no-first-run",
)


def is_loopback_host(host: str | None) -> bool:
    """Return True for ``localhost`` and loopback IP literals."""
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def is_loopback_url(url: str) -> bool:
    """Return True if ``url`` points at a loopback host (any scheme/port)."""
    return is_loopback_host(urlsplit(url).hostname)


def origin(url: str) -> str:
    """Return ``scheme://host:port`` of a URL."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


@dataclass
class GuardLog:
    """What the guards refused, for assertions and the capture report."""

    blocked: list[str] = field(default_factory=list)
    blocked_websockets: list[str] = field(default_factory=list)


async def install_guards(context: BrowserContext, allowed_origin: str, log: GuardLog) -> None:
    """Allow only ``allowed_origin`` (which must be loopback) in ``context``."""
    if not is_loopback_url(allowed_origin):
        msg = f"refusing to allow a non-loopback origin: {allowed_origin}"
        raise ValueError(msg)

    async def on_request(route: Route) -> None:
        url = route.request.url
        if url.startswith(("data:", "blob:", "about:")) or origin(url) == allowed_origin:
            await route.continue_()
            return
        log.blocked.append(url)
        await route.abort("blockedbyclient")

    async def on_websocket(ws: WebSocketRoute) -> None:
        log.blocked_websockets.append(ws.url)
        await ws.close(code=1008, reason="blocked by capture guard")

    await context.route("**/*", on_request)
    await context.route_web_socket(re.compile(".*"), on_websocket)
