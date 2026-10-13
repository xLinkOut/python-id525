"""Diagnostics (``self-diag`` / ``self-ping`` / ``self-tracert`` pages).

Every operation here is an *action*: the router generates traffic (ICMP,
traceroute) or probes its interfaces, so a read-only client refuses them.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, Page, uses
from ..models import _raw
from ..parsers import clean_str, extract_js_values, parse_int
from .base import Section, invalid

if TYPE_CHECKING:
    from collections.abc import Mapping

_NUMERIC_VAR_RE = re.compile(r"\bvar\s+(\w+)\s*=\s*(-?\d+)\s*;")

# self-diag.html pingTest(): the self test pings a fixed host once.
SELF_TEST_PING_HOST = "www.google.com"
SELF_TEST_PING_COUNT = 1
SELF_TEST_PING_SIZE = 8


@dataclass(frozen=True, slots=True, kw_only=True)
class PingDefaults:
    """Form defaults the router embeds in ``self-ping.html``."""

    host: str | None
    count: int | None
    size: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PingReport:
    """Result of :meth:`DiagnosticsApi.ping`."""

    host: str
    count: int
    size: int
    lines: tuple[str, ...]
    """One ``ping_result`` line per echo, as the router formats it."""
    completed: bool
    """False if the router answered ``result: false`` (the UI prints "fail")."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TracerouteReport:
    """Result of :meth:`DiagnosticsApi.traceroute`."""

    host: str
    output: str | None
    """The router's ``trace_result`` text (may contain HTML line breaks)."""
    completed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ConnectivityCheck:
    """Interface state from ``req_DiagnosticConnectedTest``."""

    ethernet: bool
    wifi: bool
    usb: bool
    cellular: bool
    """True if the router's cellular state mentions "Connected" or "Roaming"."""
    cellular_state: str | None
    ethernet_wan: bool
    raw: Mapping[str, Any] = _raw()


@dataclass(frozen=True, slots=True, kw_only=True)
class SelfTestReport:
    """Result of the self-diagnostics sequence (``self-diag`` page)."""

    model: str | None
    """``IDU`` / ``ODU`` / ``MiFi``: decides which interfaces the UI shows."""
    connections: ConnectivityCheck | None
    """``None`` if the router answered ``result: false``."""
    internet: bool
    """The router could ping ``www.google.com``."""
    cpu_usage: str | None
    """CPU usage as the router formats it, ``None`` if the test failed."""

    @property
    def passed(self) -> bool:
        """Return the UI's overall verdict: Internet reachable and cellular connected."""
        return self.internet and self.connections is not None and self.connections.cellular


def parse_ping_page(html: str) -> PingDefaults:
    """Parse the form defaults of ``self-ping.html``."""
    numbers = {m.group(1): int(m.group(2)) for m in _NUMERIC_VAR_RE.finditer(html)}
    return PingDefaults(
        host=clean_str(extract_js_values(html).get("pingHost")),
        count=numbers.get("pingCount"),
        size=numbers.get("pingSize"),
    )


def parse_traceroute_page(html: str) -> str | None:
    """Return the default traceroute target of ``self-tracert.html``."""
    return clean_str(extract_js_values(html).get("traceHost"))


def parse_diag_page(html: str) -> str | None:
    """Return the device model of ``self-diag.html`` (``IDU``, ``ODU``, ``MiFi``)."""
    return clean_str(extract_js_values(html).get("model"))


def parse_connectivity(data: Mapping[str, Any]) -> ConnectivityCheck:
    """Parse a ``req_DiagnosticConnectedTest`` answer like ``connectedTest_response``."""
    cellular = str(data.get("cellularConnected") or "")
    return ConnectivityCheck(
        ethernet=parse_int(data.get("ethConnected")) == 1,
        wifi=parse_int(data.get("wifiConnected")) == 1,
        usb=parse_int(data.get("usbConnected")) == 1,
        cellular="Connected" in cellular or "Roaming" in cellular,
        cellular_state=clean_str(cellular),
        ethernet_wan=parse_int(data.get("ethWanConnected")) == 1,
        raw=data,
    )


def _ping_body(host: str, count: int, size: int) -> Any:
    def body(token: str | None) -> dict[str, Any]:
        return {TOKEN_FIELD: token, "pingCount": count, "pingHost": host, "pingSize": size}

    return body


class DiagnosticsApi(Section):
    """Ping, traceroute and the self-diagnostics sequence."""

    _trace_id = 0

    @uses(Page.PING)
    async def get_ping_defaults(self) -> PingDefaults:
        """Return the ping form defaults (host, count, packet size)."""
        return parse_ping_page(await self._client._page(Page.PING))

    @uses(Page.PING, Endpoint.PING)
    async def ping(
        self,
        host: str | None = None,
        count: int | None = None,
        size: int | None = None,
        *,
        interval: float = 1.0,
    ) -> PingReport:
        """Ping ``host`` from the router, like the ``self-ping`` page.

        Omitted arguments take the page's defaults. As in the UI, the router is
        asked ``count + 1`` times (one echo per request, ``interval`` seconds
        apart) and the answer to the last request is discarded.
        """
        if host is None or count is None or size is None:
            defaults = await self.get_ping_defaults()
            host = (defaults.host or "") if host is None else host
            count = (defaults.count or 0) if count is None else count
            size = (defaults.size or 0) if size is None else size
        # the UI's checks (testStart)
        if not host:
            invalid("the host is empty")
        if size <= 0:
            invalid("the packet size must be positive")
        if count <= 0:
            invalid("the count must be positive")

        lines: list[str] = []
        for sent in range(count + 1):
            if sent:
                await asyncio.sleep(interval)
            data = await self._client._call(Endpoint.PING, _ping_body(host, count, size))
            if not data.get("result"):  # pingTest_response
                return PingReport(
                    host=host, count=count, size=size, lines=tuple(lines), completed=False
                )
            if sent < count:
                lines.append(str(data.get("ping_result") or ""))
        return PingReport(host=host, count=count, size=size, lines=tuple(lines), completed=True)

    @uses(Page.TRACEROUTE, Endpoint.TRACEROUTE)
    async def traceroute(self, host: str | None = None) -> TracerouteReport:
        """Run a traceroute from the router (the page default target if omitted).

        The router answers only when the trace is over, which can take minutes
        (the UI warns after 2 and 5): create the client with a large enough
        ``request_timeout``.
        """
        if host is None:
            host = parse_traceroute_page(await self._client._page(Page.TRACEROUTE)) or ""
        if not host:
            invalid("the host is empty")
        self._trace_id += 1
        trace_id = self._trace_id

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "traceHost": host, "traceRouteID": trace_id}

        data = await self._client._call(Endpoint.TRACEROUTE, body)
        # The UI does not trust this answer's token: it calls token_query next.
        self._client._token = None
        if not data.get("result"):
            return TracerouteReport(host=host, output=None, completed=False)
        if parse_int(data.get("traceRouteID")) != trace_id:  # a stale run: the UI ignores it
            return TracerouteReport(host=host, output=None, completed=False)
        output = str(data.get("trace_result") or "")
        return TracerouteReport(host=host, output=output, completed=True)

    @uses(Endpoint.DIAG_CONNECTED)
    async def check_connections(self) -> ConnectivityCheck | None:
        """Ask the router which interfaces are connected (``None`` if it refused)."""
        data = await self._client._call(Endpoint.DIAG_CONNECTED)
        return parse_connectivity(data) if data.get("result") else None

    @uses(Page.DIAGNOSTICS, Endpoint.DIAG_CONNECTED, Endpoint.PING, Endpoint.CPU_USAGE_TEST)
    async def run_self_test(self) -> SelfTestReport:
        """Run the ``self-diag`` sequence: interfaces, Internet ping, CPU load."""
        model = parse_diag_page(await self._client._page(Page.DIAGNOSTICS))
        connections = await self.check_connections()
        ping = await self._client._call(
            Endpoint.PING,
            _ping_body(SELF_TEST_PING_HOST, SELF_TEST_PING_COUNT, SELF_TEST_PING_SIZE),
        )
        cpu = await self._client._call(Endpoint.CPU_USAGE_TEST)
        return SelfTestReport(
            model=model,
            connections=connections,
            internet=bool(ping.get("result")),
            cpu_usage=clean_str(cpu.get("CPU_Usage")) if cpu.get("result") else None,
        )
