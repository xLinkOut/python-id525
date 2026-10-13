"""Dynamic DNS (``fw-ddns`` page).

The page holds only the registration status; the configuration comes from
``get_ddns_config.cgi``, which the UI calls on load (the password is returned
in clear text, and shown in the UI).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, Page, uses
from ..models import _raw
from ..parsers import clean_str, extract_js_values
from .base import Section, invalid

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_FIELD_LENGTH = 63
"""The UI refuses host name, user name and password of 64 characters or more."""

DDNS_SERVERS = ("dyndns.org", "dtdns.com", "zoneedit.com", "no-ip.com", "afraid.org-v2-basic")
"""Providers the UI offers (it shows ``afraid.org-v2-basic`` as ``afraid.org``)."""

_HOST_RE = re.compile(r"^[A-Za-z0-9-.]+$")  # isValidInput
_ILLEGAL_RE = re.compile(r"['\"`%&+;:,<>?]")  # ddns_save: user name / password


@dataclass(frozen=True, slots=True, kw_only=True)
class DdnsSettings:
    """Dynamic DNS configuration (``get_ddns_config.cgi``) and status (page)."""

    enabled: bool
    hostname: str
    username: str
    password: str
    server: str
    """Provider, one of :data:`DDNS_SERVERS` (``afraid.org`` may also appear)."""
    status: str | None
    """Registration status from the page (``good``, ``nochg``, ``nohost``,
    ``badauth``, ``abuse``, ``nointernet``...; anything else means idle)."""
    raw: Mapping[str, Any] = _raw()


def _wire_server(server: str) -> str:
    """Map ``afraid.org`` back to ``afraid.org-v2-basic``, as the UI does on save."""
    return "afraid.org-v2-basic" if server in ("afraid.org", "afraid.org-v2-basic") else server


class DdnsApi(Section):
    """Dynamic DNS."""

    async def _config(self) -> dict[str, Any]:
        data = await self._client._call(Endpoint.DDNS_GET)
        return {k: v for k, v in data.items() if k != TOKEN_FIELD}

    @uses(Page.DDNS, Endpoint.DDNS_GET)
    async def get_settings(self) -> DdnsSettings:
        """Return the DDNS configuration (password included) and status."""
        values = extract_js_values(await self._client._page(Page.DDNS))
        config = await self._config()
        return DdnsSettings(
            enabled=str(config.get("ddns_enable")) == "1",
            hostname=str(config.get("ddns_host_name") or ""),
            username=str(config.get("ddns_user_name") or ""),
            password=str(config.get("ddns_password") or ""),
            server=str(config.get("ddns_url") or ""),
            status=clean_str(values.get("ddns_status")),
            raw={**config, "page": values},
        )

    @uses(Endpoint.DDNS_GET, Endpoint.DDNS_SET)
    async def set_settings(
        self,
        *,
        enabled: bool | None = None,
        hostname: str | None = None,
        username: str | None = None,
        password: str | None = None,
        server: str | None = None,
    ) -> None:
        """Change the DDNS configuration; omitted fields keep their current value.

        Runs the UI's checks first (``ddns_save``). Like the UI, the host name
        must be valid even when disabling DDNS.
        """
        if server is not None and _wire_server(server) not in DDNS_SERVERS:
            invalid(f"unknown DDNS provider {server!r}; choose from {', '.join(DDNS_SERVERS)}")
        current = await self._config()
        new_host = str(current.get("ddns_host_name") or "") if hostname is None else hostname
        new_user = str(current.get("ddns_user_name") or "") if username is None else username
        new_pwd = str(current.get("ddns_password") or "") if password is None else password
        new_server = str(current.get("ddns_url") or "") if server is None else server
        if len(new_host) > MAX_FIELD_LENGTH:
            invalid("the host name is longer than 63 characters")
        if not _HOST_RE.match(new_host):
            invalid(f"invalid host name {new_host!r}: only letters, digits, '-' and '.'")
        if len(new_user) > MAX_FIELD_LENGTH:
            invalid("the user name is longer than 63 characters")
        if _ILLEGAL_RE.search(new_user):
            invalid("the user name contains an illegal symbol (one of '\"`%&+;:,<>?)")
        if len(new_pwd) > MAX_FIELD_LENGTH:
            invalid("the password is longer than 63 characters")
        if _ILLEGAL_RE.search(new_pwd):
            invalid("the password contains an illegal symbol (one of '\"`%&+;:,<>?)")
        # Untouched switch: the UI resends get_ddns_config's value as is.
        status = current.get("ddns_enable") if enabled is None else ("1" if enabled else "0")

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "DDNS_Status": status,
                "DDNS_Hostname": new_host,
                "DDNS_Login": new_user,
                "DDNS_Auth": new_pwd,
                "DDNS_Server": _wire_server(new_server),
            }

        await self._client._command(Endpoint.DDNS_SET, body)
