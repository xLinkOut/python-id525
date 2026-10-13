"""The test-suite network guard must make the real router unreachable."""

from __future__ import annotations

import socket

import aiohttp
import pytest

from id525 import Id525Client, Id525ConnectionError
from id525.const import DEFAULT_HOST

from . import netguard

# TEST-NET-1 (RFC 5737): reserved for documentation, never routed. Used as the
# "forbidden" target; the router's own address is never dialled, not even here.
FORBIDDEN = "192.0.2.1"


@pytest.mark.parametrize(
    ("address", "allowed"),
    [
        ((DEFAULT_HOST, 443), False),
        (("192.168.224.1", 80), False),
        ((FORBIDDEN, 80), False),
        (("example.com", 443), False),
        (("::ffff:192.168.224.1", 443, 0, 0), False),
        (("127.0.0.1", 8080), True),
        (("127.0.0.2", 8080), True),
        (("::1", 8080, 0, 0), True),
        (("localhost", 8080), True),
        ("/tmp/some.sock", True),
    ],
)
def test_classification(address: object, allowed: bool) -> None:
    assert netguard.is_allowed(address) is allowed


def test_guard_is_installed() -> None:
    assert socket.socket.connect.__module__ == netguard.__name__


def test_raw_socket_is_refused_before_connecting() -> None:
    before = len(netguard.blocked)
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(netguard.NetworkGuardError),
    ):
        sock.connect((FORBIDDEN, 80))
    assert netguard.blocked[before:] == [(FORBIDDEN, 80)]


def test_udp_sendto_is_refused() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock,
        pytest.raises(netguard.NetworkGuardError),
    ):
        sock.sendto(b"x", (FORBIDDEN, 53))


async def test_aiohttp_is_refused() -> None:
    before = len(netguard.blocked)
    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        with pytest.raises(aiohttp.ClientConnectorError):
            await http.get(f"http://{FORBIDDEN}/")
    assert (FORBIDDEN, 80) in netguard.blocked[before:]


async def test_client_with_default_host_cannot_reach_the_router() -> None:
    """A test that forgets ``host`` must fail fast, not talk to the router."""
    before = len(netguard.blocked)
    client = Id525Client(password="x", request_timeout=5)
    with pytest.raises(Id525ConnectionError):
        await client.login()
    await client.close()
    assert [a for a in netguard.blocked[before:] if a[0] == DEFAULT_HOST]  # type: ignore[index]
