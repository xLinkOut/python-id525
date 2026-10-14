"""Process-wide network guard for the test suite: loopback only.

The router is production equipment and must never be contacted by tests (not
even for reads). This guard is installed by ``conftest.py`` before any test
runs. It wraps ``socket.connect`` / ``connect_ex`` / ``sendto`` and refuses any
destination that is not a loopback address or a Unix socket, *before* the
syscall, so no packet ever leaves the machine. asyncio and aiohttp end up in
``socket.connect`` too, so every client in the suite is covered.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

_ORIGINALS: dict[str, Any] = {}
blocked: list[object] = []
"""Every refused destination, for assertions."""


class NetworkGuardError(ConnectionRefusedError):
    """A test tried to reach a non-loopback address."""


def is_allowed(address: object) -> bool:
    """Return True for loopback IPs, ``localhost`` and Unix-socket paths."""
    if isinstance(address, str | bytes):  # AF_UNIX path
        return True
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # a hostname other than localhost: refuse rather than resolve


def _check(address: object) -> None:
    if not is_allowed(address):
        blocked.append(address)
        msg = f"network guard: tests may only connect to loopback, not {address!r}"
        raise NetworkGuardError(msg)


def install() -> None:
    """Patch the socket class (idempotent)."""
    if _ORIGINALS:
        return
    cls = socket.socket
    _ORIGINALS.update(connect=cls.connect, connect_ex=cls.connect_ex, sendto=cls.sendto)

    def connect(self: socket.socket, address: Any) -> None:
        _check(address)
        _ORIGINALS["connect"](self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        _check(address)
        result: int = _ORIGINALS["connect_ex"](self, address)
        return result

    def sendto(self: socket.socket, data: Any, *args: Any) -> int:
        _check(args[-1])
        result: int = _ORIGINALS["sendto"](self, data, *args)
        return result

    cls.connect = connect  # type: ignore[method-assign,assignment]
    cls.connect_ex = connect_ex  # type: ignore[method-assign,assignment]
    cls.sendto = sendto  # type: ignore[assignment]
