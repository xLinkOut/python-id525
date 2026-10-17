"""Port forwarding and DMZ (``fw-portfwd`` page)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, Page, uses
from ..models import _raw
from ..parsers import clean_str, extract_js_values, parse_int
from .base import Section, invalid

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_PORT_FORWARD_RULES = 10
MAX_PORT = 65535
# UI IPv4_CIDR: a dotted quad, optionally with a /prefix (which the UI accepts).
_IPV4_CIDR_RE = re.compile(
    r"^(?=\d+\.\d+\.\d+\.\d+($|\/))(([1-9]?\d|1\d\d|2[0-4]\d|25[0-5])\.?){4}"
    r"(\/([0-9]|[1-2][0-9]|3[0-2]))?$"
)
_NUMERIC_VAR_RE = re.compile(r"\bvar\s+(\w+)\s*=\s*(-?\d+)\s*;")
_JS_INT_RE = re.compile(r"^\s*([+-]?\d+)")


class PortForwardProtocol(StrEnum):
    """Forwarded protocol."""

    TCP = "tcp"
    UDP = "udp"
    BOTH = "both"

    @property
    def wire(self) -> str:
        """Return the value the router uses (``protocol``: ``"0"``/``"1"``/``"2"``)."""
        return {"tcp": "0", "udp": "1", "both": "2"}[self.value]

    @classmethod
    def from_wire(cls, value: object) -> PortForwardProtocol:
        """Map the rule's numeric protocol (the UI treats anything else as TCP)."""
        return {1: cls.UDP, 2: cls.BOTH}.get(parse_int(value) or 0, cls.TCP)


@dataclass(frozen=True, slots=True, kw_only=True)
class PortForwardRule:
    """One port-forwarding entry."""

    instance: Any
    """Router-side id (``edit_instance`` / ``del_instance``)."""
    wan_port: int | None
    wan_port_end: int
    """Last port of a WAN port range, ``0`` for a single port."""
    lan_ip: str
    lan_port: int | None
    protocol: PortForwardProtocol
    enabled: bool
    description: str | None
    raw: Mapping[str, Any] = _raw()


@dataclass(frozen=True, slots=True, kw_only=True)
class PortForwardingSettings:
    """Port forwarding and DMZ as shown by the ``fw-portfwd`` page."""

    enabled: bool
    dmz_enabled: bool
    dmz_ip: str | None
    rules: tuple[PortForwardRule, ...]
    router_ip: str | None
    raw: Mapping[str, Any] = _raw()


def parse_port_forwarding_page(html: str) -> PortForwardingSettings:
    """Parse the data the router embeds in ``fw-portfwd.html``."""
    values: dict[str, Any] = extract_js_values(html)
    values.update({m.group(1): int(m.group(2)) for m in _NUMERIC_VAR_RE.finditer(html)})
    entries = json.loads(str(values.get("port_fwd_entries", "[]")).replace("&quot;", '"'))
    rules = tuple(
        PortForwardRule(
            instance=entry.get("instance"),
            wan_port=parse_int(entry.get("externalPort")),
            wan_port_end=parse_int(entry.get("externalPortEndRange")) or 0,
            lan_ip=str(entry.get("internalClient", "")),
            lan_port=parse_int(entry.get("internalPort")),
            protocol=PortForwardProtocol.from_wire(entry.get("protocol")),
            enabled=parse_int(entry.get("enable")) == 1,
            description=clean_str(entry.get("description"))
            if entry.get("description") != "---"
            else None,
            raw=entry,
        )
        for entry in entries or []
    )
    return PortForwardingSettings(
        enabled=values.get("port_forward_status") not in (None, "", "0"),
        dmz_enabled=values.get("dmz_status") == "1",
        dmz_ip=clean_str(values.get("ip_dmz")),
        rules=rules,
        router_ip=clean_str(values.get("host_ip")),
        raw=values,
    )


def _js_int(value: str) -> int | None:
    """JavaScript ``parseInt``: leading digits, else ``None`` (NaN)."""
    match = _JS_INT_RE.match(value)
    return int(match.group(1)) if match else None


def _check_port(port: int, what: str) -> None:
    if not 1 <= port <= MAX_PORT:
        invalid(f"the {what} must be between 1 and {MAX_PORT}")


def _check_range(wan_port: int, wan_port_end: int) -> None:
    if wan_port_end:
        _check_port(wan_port_end, "last WAN port")
        if wan_port >= wan_port_end:
            invalid("the last WAN port must be greater than the first one")


def _check_lan_ip(settings: PortForwardingSettings, lan_ip: str) -> None:
    """UI checks on the LAN address, in order (after the empty check)."""
    reference = str(settings.raw.get("startIP", "")).split(".")
    octets = lan_ip.split(".")
    class_index = settings.raw.get("ip_class_index", 1)
    for i in range(4):
        if i <= class_index:
            mine = _js_int(octets[i]) if i < len(octets) else None
            theirs = _js_int(reference[i]) if i < len(reference) else None
            if mine is None or mine != theirs:  # NaN != anything
                invalid(f"{lan_ip} is not in the router's LAN")
    if not _IPV4_CIDR_RE.match(lan_ip):
        invalid(f"invalid IP address {lan_ip!r}")
    if _js_int(octets[3]) in (0, 255):
        invalid(f"{lan_ip} is a network or broadcast address")
    if lan_ip == settings.router_ip:
        invalid(f"{lan_ip} is the router itself")


class PortForwardingApi(Section):
    """Port forwarding rules, their master switch, and the DMZ host."""

    @uses(Page.PORT_FORWARDING)
    async def get_settings(self) -> PortForwardingSettings:
        """Return the DMZ, the forwarding switch and the rules."""
        return parse_port_forwarding_page(await self._client._page(Page.PORT_FORWARDING))

    async def _dmz(self, *, enabled: bool, ip: str | None) -> None:
        current = await self.get_settings()
        address = (current.dmz_ip or "") if ip is None else ip
        if enabled:
            octets = address.split(".")
            if address == current.router_ip or len(octets) != 4:
                invalid(f"invalid DMZ host {address!r}")
            for octet in octets:
                value = _js_int(octet)
                if value is None or not 0 < value < 255:
                    invalid(f"invalid DMZ host {address!r}")

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "DmzSta": "1" if enabled else "0", "DmzIP": address}

        await self._client._command(Endpoint.DMZ_SAVE, body)

    @uses(Page.PORT_FORWARDING, Endpoint.DMZ_SAVE)
    async def enable_dmz(self, ip: str | None = None) -> None:
        """Expose ``ip`` (default: the current DMZ host) to every unsolicited WAN packet."""
        await self._dmz(enabled=True, ip=ip)

    @uses(Page.PORT_FORWARDING, Endpoint.DMZ_SAVE)
    async def disable_dmz(self) -> None:
        """Turn the DMZ off (the host address is kept).

        Like the UI, this sends the current host back. If no DMZ host was ever
        set, the router refuses that (``Id525CommandError``, "Invalid
        Static_IP"; seen live) although the DMZ is already off.
        """
        await self._dmz(enabled=False, ip=None)

    async def _status(self, *, enabled: bool) -> None:
        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "isPFEnable": "1" if enabled else "0"}

        await self._client._command(Endpoint.PORTFWD_STATUS, body)

    @uses(Endpoint.PORTFWD_STATUS)
    async def enable(self) -> None:
        """Turn port forwarding on (the rules are kept)."""
        await self._status(enabled=True)

    @uses(Endpoint.PORTFWD_STATUS)
    async def disable(self) -> None:
        """Turn port forwarding off (the rules are kept)."""
        await self._status(enabled=False)

    @uses(Page.PORT_FORWARDING, Endpoint.PORTFWD_ADD)
    async def add_rule(
        self,
        wan_port: int,
        lan_ip: str,
        lan_port: int,
        *,
        wan_port_end: int = 0,
        protocol: PortForwardProtocol | str = PortForwardProtocol.BOTH,
        enabled: bool = True,
    ) -> None:
        """Forward WAN port ``wan_port`` (to ``wan_port_end`` if non-zero) to ``lan_ip:lan_port``.

        Runs the UI's checks first (``btnOKClicked``).
        """
        proto = PortForwardProtocol(protocol)
        current = await self.get_settings()
        if len(current.rules) >= MAX_PORT_FORWARD_RULES:
            invalid(f"the router holds at most {MAX_PORT_FORWARD_RULES} port-forwarding rules")
        _check_port(wan_port, "WAN port")
        _check_range(wan_port, wan_port_end)
        if not lan_ip:
            invalid("the LAN IP address is empty")
        _check_port(lan_port, "LAN port")
        _check_lan_ip(current, lan_ip)

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "global_port": wan_port,
                "global_port_range": wan_port_end,
                "private_port": lan_port,
                "ipAddr": lan_ip,
                "protocol": proto.wire,
                "isEnabled": 1 if enabled else 0,
            }

        await self._client._command(Endpoint.PORTFWD_ADD, body)

    @uses(Page.PORT_FORWARDING, Endpoint.PORTFWD_EDIT)
    async def modify_rule(
        self,
        instance: int,
        *,
        wan_port: int | None = None,
        wan_port_end: int | None = None,
        lan_ip: str | None = None,
        lan_port: int | None = None,
        protocol: PortForwardProtocol | str | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Change a rule (``instance`` is :attr:`PortForwardRule.instance`).

        Omitted fields are kept; ``wan_port_end=0`` turns a range into a single
        port. The UI resends every field. Runs the UI's checks first
        (``edit_rule_save``).
        """
        current = await self.get_settings()
        rule = next((r for r in current.rules if r.instance == instance), None)
        if rule is None:
            invalid(f"no port-forwarding rule with instance {instance}")
        new_wan = (rule.wan_port or 0) if wan_port is None else wan_port
        new_end = rule.wan_port_end if wan_port_end is None else wan_port_end
        new_ip = rule.lan_ip if lan_ip is None else lan_ip
        new_lan = (rule.lan_port or 0) if lan_port is None else lan_port
        proto = rule.protocol if protocol is None else PortForwardProtocol(protocol)
        new_enabled = rule.enabled if enabled is None else enabled
        _check_port(new_wan, "WAN port")
        _check_port(new_lan, "LAN port")
        _check_range(new_wan, new_end)
        if not new_ip:
            invalid("the LAN IP address is empty")
        _check_lan_ip(current, new_ip)

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "edit_instance": _js_int(str(rule.instance)),
                "global_port": new_wan,
                "global_port_range": new_end,
                "private_port": new_lan,
                "ipAddr": new_ip,
                "protocol": proto.wire,
                "isEnabled": 1 if new_enabled else 0,
            }

        await self._client._command(Endpoint.PORTFWD_EDIT, body)

    @uses(Page.PORT_FORWARDING, Endpoint.PORTFWD_DELETE)
    async def delete_rule(self, instance: int) -> None:
        """Delete a rule (``instance`` is :attr:`PortForwardRule.instance`)."""
        current = await self.get_settings()
        rule = next((r for r in current.rules if r.instance == instance), None)
        if rule is None:
            invalid(f"no port-forwarding rule with instance {instance}")

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "del_instance": rule.instance}

        await self._client._command(Endpoint.PORTFWD_DELETE, body)
