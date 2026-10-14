"""self-diag.html: interface check, Internet ping and CPU load."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

CONNECTED = {
    "ethConnected": 1,
    "wifiConnected": 1,
    "usbConnected": 0,
    "cellularConnected": "Connected",
    "ethWanConnected": 0,
}
DISCONNECTED = {
    "ethConnected": 0,
    "wifiConnected": 0,
    "usbConnected": 0,
    "cellularConnected": "Disconnected",
    "ethWanConnected": 1,
}


async def self_test(page: BrowserPage, inputs: dict[str, Any]) -> None:
    del inputs
    await click(page, f"{await platform_prefix(page)}-TestStartBtn")


async def connections_only(page: BrowserPage, inputs: dict[str, Any]) -> None:
    """Start, then Stop at once: the interface check already queued still runs."""
    del inputs
    button = f"{await platform_prefix(page)}-TestStartBtn"
    await click(page, button)
    await asyncio.sleep(0.1)
    await click(page, button)


SCENARIOS = [
    Scenario(
        name="self_test_pass",
        page=Page.DIAGNOSTICS,
        endpoint=Endpoint.CPU_USAGE_TEST,
        call="diagnostics.run_self_test",
        inputs={},
        drive=self_test,
        answers={
            "req_DiagnosticConnectedTest": CONNECTED,
            "req_pingTest": {"ping_result": "64 bytes from 142.250.0.1: seq=0 ttl=117"},
            "req_cpuUsageTest": {"CPU_Usage": "12%"},
        },
        notes="connected test, then a fixed ping (www.google.com, 1 x 8 bytes), then CPU",
    ),
    Scenario(
        name="self_test_fail",
        page=Page.DIAGNOSTICS,
        endpoint=Endpoint.PING,
        call="diagnostics.run_self_test",
        inputs={},
        drive=self_test,
        answers={
            "req_DiagnosticConnectedTest": DISCONNECTED,
            "req_pingTest": {"result": False},
            "req_cpuUsageTest": {"result": False},
        },
        notes="failed steps do not stop the sequence",
    ),
    Scenario(
        name="check_connections",
        page=Page.DIAGNOSTICS,
        endpoint=Endpoint.DIAG_CONNECTED,
        call="diagnostics.check_connections",
        inputs={},
        drive=connections_only,
        answers={"req_DiagnosticConnectedTest": CONNECTED},
    ),
    Scenario(
        name="check_connections_roaming",
        page=Page.DIAGNOSTICS,
        endpoint=Endpoint.DIAG_CONNECTED,
        call="diagnostics.check_connections",
        inputs={},
        drive=connections_only,
        answers={"req_DiagnosticConnectedTest": {**DISCONNECTED, "cellularConnected": "Roaming"}},
    ),
]
