"""Shared plumbing for the per-page API sections."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NoReturn

from ..exceptions import Id525ValidationError

if TYPE_CHECKING:
    from ..client import Id525Client
    from ..endpoints import Endpoint

# Validators ported verbatim from the web UI (js/scriptGeneric.js) so the client
# refuses exactly what the UI refuses, before anything is sent.
_MAC_RE = re.compile(r"^([0-9a-f]{2}([:]|$)){6}$", re.IGNORECASE)  # checkMACFormat
_IPV4_RE = re.compile(  # validateIPaddress
    r"^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\."
    r"(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
)
_DEVICE_NAME_FORBIDDEN = "`~!@#$%^&*()=+_[]{}\\|;:.'\",<>/?-"  # validateDeviceNameStr


def is_mac(value: str) -> bool:
    """UI ``checkMACFormat``: six colon-separated hex pairs."""
    return bool(_MAC_RE.match(value))


def is_ipv4(value: str) -> bool:
    """UI ``validateIPaddress``: dotted quad, octets 0-255."""
    return bool(_IPV4_RE.match(value))


def is_device_name(value: str) -> bool:
    """UI ``validateDeviceNameStr``: no punctuation from the UI's deny-list."""
    return not any(c in _DEVICE_NAME_FORBIDDEN for c in value)


def ip_cmp(ip1: str, ip2: str) -> int:
    """UI ``ipCmp`` (js/validate.js): -1, 0 or 1, octet by octet."""
    for a, b in zip(ip1.split("."), ip2.split("."), strict=False):
        if int(a) != int(b):
            return 1 if int(a) > int(b) else -1
    return 0


def invalid(message: str) -> NoReturn:
    """Raise the error used for inputs the UI would refuse."""
    raise Id525ValidationError(message)


class Section:
    """A group of operations backed by one UI page."""

    def __init__(self, client: Id525Client) -> None:
        self._client = client

    def _unsupported(self, endpoint: Endpoint) -> NoReturn:
        """Raise for endpoints that are deliberately not implemented."""
        info = endpoint.info
        msg = f"{endpoint} is not supported ({info.status}): {info.summary}"
        raise NotImplementedError(msg)
