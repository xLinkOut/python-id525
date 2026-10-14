from __future__ import annotations

import json

import pytest

from id525.sections.diagnostics import (
    ConnectivityCheck,
    SelfTestReport,
    parse_connectivity,
    parse_diag_page,
    parse_ping_page,
    parse_traceroute_page,
)

from .conftest import ClientFactory, FakeRouter, load_fixture


def test_page_defaults() -> None:
    defaults = parse_ping_page(load_fixture("self-ping.html"))
    assert (defaults.host, defaults.count, defaults.size) == ("192.168.224.1", 10, 32)
    assert parse_traceroute_page(load_fixture("self-tracert.html")) == "8.8.8.8"
    assert parse_diag_page(load_fixture("self-diag.html")) == "IDU"


async def test_ping_collects_all_but_the_last_answer(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    router.answers["req_pingTest"] = [{"ping_result": f"line {i}"} for i in range(1, 4)]
    client = await make_client(read_only=False)
    report = await client.diagnostics.ping("192.0.2.7", 2, 16, interval=0)
    assert report.lines == ("line 1", "line 2")
    assert report.completed is True
    assert router.count("req_pingTest") == 3
    assert "page:self-ping" not in router.calls  # nothing omitted: no page load


async def test_ping_uses_page_defaults(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client(read_only=False)
    report = await client.diagnostics.ping(count=1, interval=0)
    assert (report.host, report.size) == ("192.168.224.1", 32)
    assert router.count("page:self-ping") == 1


async def test_ping_stops_on_failure(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers["req_pingTest"] = [{"ping_result": "ok"}, {"result": False}]
    client = await make_client(read_only=False)
    report = await client.diagnostics.ping("192.0.2.7", 5, 8, interval=0)
    assert (report.lines, report.completed) == (("ok",), False)
    assert router.count("req_pingTest") == 2


async def test_traceroute(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers["req_traceRouteTest"] = [
        {"trace_result": "first", "traceRouteID": 1},
        {"trace_result": "stale", "traceRouteID": 1},
    ]
    client = await make_client(read_only=False)
    first = await client.diagnostics.traceroute("example.com")
    assert (first.output, first.completed) == ("first", True)
    second = await client.diagnostics.traceroute("example.com")  # sends traceRouteID 2
    assert (second.output, second.completed) == (None, False)
    ids = [json.loads(b)["traceRouteID"] for n, b in router.bodies if n == "req_traceRouteTest"]
    assert ids == [1, 2]
    # like the UI, a fresh token is fetched after each traceroute
    calls = router.calls
    assert calls[calls.index("req_traceRouteTest") + 1] == "token_query"


async def test_check_connections_refused(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers["req_DiagnosticConnectedTest"] = {"result": False}
    client = await make_client(read_only=False)
    assert await client.diagnostics.check_connections() is None


@pytest.mark.parametrize(
    ("state", "connected"),
    [("Connected", True), ("Connected (Roaming)", True), ("Roaming", True), ("Searching", False)],
)
def test_cellular_state(state: str, connected: bool) -> None:
    assert parse_connectivity({"cellularConnected": state}).cellular is connected


def test_self_test_verdict() -> None:
    online = parse_connectivity({"cellularConnected": "Connected", "ethConnected": 1})
    offline = parse_connectivity({"cellularConnected": "Disconnected"})
    assert online.ethernet
    assert not online.wifi

    def report(connections: ConnectivityCheck | None, *, internet: bool) -> SelfTestReport:
        return SelfTestReport(
            model="IDU", connections=connections, internet=internet, cpu_usage=None
        )

    assert report(online, internet=True).passed
    assert not report(online, internet=False).passed
    assert not report(offline, internet=True).passed
    assert not report(None, internet=True).passed


async def test_run_self_test(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers.update(
        {
            "req_DiagnosticConnectedTest": {"cellularConnected": "Connected", "usbConnected": 1},
            "req_cpuUsageTest": {"CPU_Usage": "7%"},
        }
    )
    client = await make_client(read_only=False)
    report = await client.diagnostics.run_self_test()
    assert report.model == "IDU"
    assert report.connections is not None
    assert report.connections.usb
    assert (report.internet, report.cpu_usage, report.passed) == (True, "7%", True)
