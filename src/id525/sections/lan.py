"""LAN / DHCP settings from the ``lan-settings`` page."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, Page, uses
from ..models import _raw
from ..parsers import clean_str, extract_entity_json, extract_js_values, parse_int
from .base import Section, invalid, ip_cmp, is_device_name, is_ipv4, is_mac

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_DHCP_RESERVATIONS = 20
MAX_DEVICE_NAME_LENGTH = 32
_UNCHANGED = "0"  # req_LanStaticAddrModify sentinel for "keep the current value"
_NUMERIC_VAR_RE = re.compile(r"\bvar\s+(\w+)\s*=\s*(-?\d+)\s*;")


@dataclass(frozen=True, slots=True, kw_only=True)
class DhcpReservation:
    """A static DHCP lease (``staticAddrList_str`` entry)."""

    index: int
    """Router-side id of the entry (``instance`` in edit / delete requests)."""
    interface_index: int
    name: str
    mac: str
    ip: str
    subnet_mask: str | None
    connection_type: str | None
    active: bool
    raw: Mapping[str, Any] = _raw()


@dataclass(frozen=True, slots=True, kw_only=True)
class LanSettings:
    """LAN configuration as shown by the ``lan-settings`` page."""

    ip: str | None
    subnet_mask: str | None
    dhcp_enabled: bool
    dhcp_start: str | None
    dhcp_end: str | None
    lease_time: int | None
    """DHCP lease time, in the unit the UI shows (minutes)."""
    dns_primary: str | None
    dns_secondary: str | None
    domain_name: str | None
    mtu: int | None
    operation_mode: str | None
    """``Router`` or ``Bridge``."""
    reservations: tuple[DhcpReservation, ...]
    raw: Mapping[str, Any] = _raw()


def parse_lan_page(html: str) -> LanSettings:
    """Parse the data the router embeds in ``lan-settings.html``."""
    values = extract_js_values(html)
    numbers = {m.group(1): int(m.group(2)) for m in _NUMERIC_VAR_RE.finditer(html)}
    reservations = tuple(
        DhcpReservation(
            index=int(entry["index"]),
            interface_index=int(entry["interface_index"]),
            name=str(entry.get("deviceName", "")),
            mac=str(entry.get("mac_addr", "")),
            ip=str(entry.get("ip_addr", "")),
            subnet_mask=clean_str(entry.get("subnetMask")),
            connection_type=clean_str(entry.get("connectionType")),
            active=parse_int(entry.get("reservationStatus")) == 1,
            raw=entry,
        )
        for entry in extract_entity_json(html, "staticAddrList_str").get(
            "dhcp_reservation_list", []
        )
    )
    return LanSettings(
        ip=clean_str(values.get("hostIP")),
        subnet_mask=clean_str(values.get("subnetMask")),
        dhcp_enabled=numbers.get("dhcp_enable_int") == 1,
        dhcp_start=clean_str(values.get("dhcp_startIP")),
        dhcp_end=clean_str(values.get("dhcp_endIP")),
        lease_time=parse_int(values.get("leaseTime")),
        dns_primary=clean_str(values.get("pri_dns")),
        dns_secondary=clean_str(values.get("sec_dns")),
        domain_name=clean_str(values.get("domainName")),
        mtu=parse_int(values.get("lan_mtu")) or None,
        operation_mode=clean_str(values.get("modeSelectType")),
        reservations=reservations,
        raw={**values, **numbers},
    )


def _in_pool(settings: LanSettings, ip: str) -> bool:
    """UI ``validateAddIPaddress``: ``dhcp_startIP <= ip <= dhcp_endIP``."""
    start, end = settings.dhcp_start or "0.0.0.0", settings.dhcp_end or "0.0.0.0"  # noqa: S104
    return ip_cmp(ip, start) != -1 and ip_cmp(ip, end) != 1


def _find(settings: LanSettings, index: int) -> tuple[int, DhcpReservation]:
    found = next(((i, e) for i, e in enumerate(settings.reservations) if e.index == index), None)
    if found is None:
        invalid(f"no DHCP reservation with index {index}")
    return found


class LanApi(Section):
    """LAN / DHCP settings and static DHCP leases."""

    @uses(Page.LAN_SETTINGS)
    async def get_settings(self) -> LanSettings:
        """Return the LAN configuration and the DHCP reservations."""
        return parse_lan_page(await self._client._page(Page.LAN_SETTINGS))

    @uses(Page.LAN_SETTINGS, Endpoint.DHCP_RESERVATION_ADD)
    async def add_dhcp_reservation(self, name: str, ip: str, mac: str) -> None:
        """Reserve ``ip`` for ``mac``. Runs the UI's checks first (``addAddrSave``)."""
        current = await self.get_settings()
        others = current.reservations
        if not is_ipv4(ip):
            invalid(f"invalid IP address {ip!r}")
        if not is_mac(mac):
            invalid(f"invalid MAC address {mac!r}")
        if not name:
            invalid("the device name is empty")
        if len(name) > MAX_DEVICE_NAME_LENGTH:
            invalid(f"the device name is longer than {MAX_DEVICE_NAME_LENGTH} characters")
        if not _in_pool(current, ip):
            invalid(f"{ip} is outside the DHCP pool {current.dhcp_start}-{current.dhcp_end}")
        if any(e.name == name for e in others):
            invalid(f"a reservation named {name!r} already exists")
        if any(e.mac.upper() == mac.upper() for e in others):
            invalid(f"{mac} already has a reservation")
        if any(e.ip == ip for e in others):
            invalid(f"{ip} is already reserved")
        if not is_device_name(name):
            invalid(f"the device name {name!r} contains forbidden characters")
        if len(others) >= MAX_DHCP_RESERVATIONS:
            invalid(f"the router holds at most {MAX_DHCP_RESERVATIONS} reservations")

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "deviceName": name,
                "Static_IP": ip,
                "MAC": mac,
                "interface_index": 1,
            }

        await self._client._command(Endpoint.DHCP_RESERVATION_ADD, body)

    @uses(Page.LAN_SETTINGS, Endpoint.DHCP_RESERVATION_MODIFY)
    async def modify_dhcp_reservation(
        self,
        index: int,
        *,
        name: str | None = None,
        ip: str | None = None,
        mac: str | None = None,
    ) -> None:
        """Change a reservation (``index`` is :attr:`DhcpReservation.index`).

        Omitted fields are kept. Runs the UI's checks first (``editAddrSave``).
        """
        current = await self.get_settings()
        position, entry = _find(current, index)
        new_name = entry.name if name is None else name
        new_ip = entry.ip if ip is None else ip
        new_mac = entry.mac if mac is None else mac
        others = [e for i, e in enumerate(current.reservations) if i != position]
        if not is_ipv4(new_ip):
            invalid(f"invalid IP address {new_ip!r}")
        if not _in_pool(current, new_ip):
            invalid(f"{new_ip} is outside the DHCP pool {current.dhcp_start}-{current.dhcp_end}")
        if not is_mac(new_mac):
            invalid(f"invalid MAC address {new_mac!r}")
        if len(new_name) > MAX_DEVICE_NAME_LENGTH:
            invalid(f"the device name is longer than {MAX_DEVICE_NAME_LENGTH} characters")
        if any(e.name == new_name for e in others):
            invalid(f"a reservation named {new_name!r} already exists")
        if any(e.mac.upper() == new_mac.upper() for e in others):
            invalid(f"{new_mac} already has a reservation")
        if any(e.ip == new_ip for e in others):
            invalid(f"{new_ip} is already reserved")
        if not is_device_name(new_name):
            invalid(f"the device name {new_name!r} contains forbidden characters")

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "deviceName": _UNCHANGED if new_name == entry.name else new_name,
                "Static_IP": _UNCHANGED if new_ip == entry.ip else new_ip,
                "editMAC": _UNCHANGED if new_mac == entry.mac else new_mac,
                "instance": entry.index,
                "interface_index": entry.interface_index,
            }

        await self._client._command(Endpoint.DHCP_RESERVATION_MODIFY, body)

    @uses(Page.LAN_SETTINGS, Endpoint.DHCP_RESERVATION_DELETE)
    async def delete_dhcp_reservation(self, index: int) -> None:
        """Delete a reservation (``index`` is :attr:`DhcpReservation.index`)."""
        _, entry = _find(await self.get_settings(), index)

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "instance": entry.index,
                "interface_id": entry.interface_index,
            }

        await self._client._command(Endpoint.DHCP_RESERVATION_DELETE, body)
