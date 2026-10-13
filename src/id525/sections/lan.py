"""LAN / DHCP settings from the ``lan-settings`` page."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, Page, uses
from ..exceptions import Id525CommandError, Id525ResponseError
from ..models import _raw
from ..parsers import clean_str, extract_js_values, parse_int
from .base import Section, invalid, ip_cmp, is_device_name, is_ipv4, is_mac

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_DHCP_RESERVATIONS = 20
MAX_DEVICE_NAME_LENGTH = 32
_UNCHANGED = "0"  # req_LanStaticAddrModify sentinel for "keep the current value"
_NUMERIC_VAR_RE = re.compile(r"\bvar\s+(\w+)\s*=\s*(-?\d+)\s*;")
_RESERVATIONS_RE = re.compile(r"\bvar\s+staticAddrList_str\s*=\s*'(.*?)'\s*;", re.S)
MIN_LEASE_TIME, MAX_LEASE_TIME = 2, 43200


class EthernetPortRole(StrEnum):
    """What the configurable Ethernet port does (``req_ethWanEnabled``)."""

    WAN = "wan"
    LAN = "lan"


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
    """``Router``, ``Bridge`` or ``Eogre``, as the UI derives it."""
    ethernet_port_role: EthernetPortRole | None
    """Role of the configurable Ethernet port (applied after a reboot)."""
    ethernet_port: int | None
    """Number of the configurable Ethernet port."""
    reservations: tuple[DhcpReservation, ...]
    raw: Mapping[str, Any] = _raw()


def _reservation_list(html: str) -> list[dict[str, Any]]:
    """Decode ``staticAddrList_str`` like the UI: ``decodeURIComponent``, then entities."""
    match = _RESERVATIONS_RE.search(html)
    if not match:
        msg = "embedded variable 'staticAddrList_str' not found in page"
        raise Id525ResponseError(msg)
    try:
        data = json.loads(unquote(match.group(1)).replace("&quot;", '"'))
    except json.JSONDecodeError as err:
        msg = "embedded variable 'staticAddrList_str' is not valid JSON"
        raise Id525ResponseError(msg) from err
    entries: list[dict[str, Any]] = data.get("dhcp_reservation_list", [])
    return entries


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
        for entry in _reservation_list(html)
    )
    # bodyLoad(): the mode comes from the numeric flags, not from modeSelectType
    if numbers.get("modeEoGRE") == 1:
        mode: str | None = "Eogre"
    elif "modeSelectType_CFG" in numbers:
        mode = "Router" if numbers["modeSelectType_CFG"] == 0 else "Bridge"
    else:
        mode = clean_str(values.get("modeSelectType"))
    port_select = values.get("ethPortSelect")
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
        operation_mode=mode,
        ethernet_port_role=(
            None
            if port_select is None
            else EthernetPortRole.WAN
            if port_select == "WAN Port"
            else EthernetPortRole.LAN
        ),
        ethernet_port=parse_int(values.get("ethWanPortIdx")),
        reservations=reservations,
        raw={**values, **numbers},
    )


_SEGMENTS = {128: 128, 192: 64, 224: 32, 240: 16, 248: 8, 252: 4, 254: 2, 255: 1}
"""UI ``cal_networkSegments``: addresses per subnet for a mask octet."""


def network_range(ip: str, mask: str, ip_class: int) -> tuple[str, str] | None:
    """UI ``get_network_brosdcast_IP_class{C,B,A}``: (network, broadcast) or None.

    Ported verbatim, quirks included: only the class's variable octet is
    considered, and the leading octets keep their original spelling.
    """
    host, net = ip.split("."), mask.split(".")
    octet = 3 - ip_class  # C: 4th octet, B: 3rd, A: 2nd
    if int(net[octet]) == 0:
        low, high = 0, 255
    else:
        size = _SEGMENTS.get(int(net[octet]), 0)
        if size == 0:
            return None
        low = int(host[octet]) // size * size
        high = low + size - 1
    head = ".".join(host[:octet])
    tail_low, tail_high = [".0"] * (3 - octet), [".255"] * (3 - octet)
    return (
        f"{head}.{low}{''.join(tail_low)}",
        f"{head}.{high}{''.join(tail_high)}",
    )


def _host_in_subnet(ip: str, mask: str, ip_class: int) -> bool:
    """UI ``checkIP_class{C,B,A}``: strictly between network and broadcast."""
    bounds = network_range(ip, mask, ip_class)
    return bounds is not None and ip_cmp(ip, bounds[0]) == 1 and ip_cmp(ip, bounds[1]) == -1


_CLASS_HOST_RANGES = {  # ipClass -> (letter, first, last host address accepted)
    0: ("C", "192.0.1.1", "223.255.255.254"),
    1: ("B", "128.0.0.1", "191.255.255.254"),
    2: ("A", "0.0.0.1", "127.255.255.254"),
}


def _bridge_dhcp_range(ip: str, start: str, end: str) -> tuple[str, str]:
    """UI ``autoChangeDHCPRangeBaseHostIP`` (class C, bridge / EoGRE mode)."""
    head = ip.split(".")[:3]
    low, high = ("20", "60") if int(ip.split(".")[3]) >= 127 else ("200", "240")
    del start, end
    return ".".join([*head, low]), ".".join([*head, high])


def _lan_save_body(  # noqa: PLR0912
    current: LanSettings,
    *,
    ip: str,
    mask: str,
    dhcp_enabled: bool,
    start: str,
    end: str,
    lease: str,
) -> dict[str, Any]:
    """Validate like UI ``internetProtoSave`` and return the body fields (no token)."""
    if not (is_ipv4(ip) and is_ipv4(mask)):
        invalid("the LAN IP address or subnet mask is invalid")
    if (
        ip == current.ip
        and mask == current.subnet_mask
        and dhcp_enabled == current.dhcp_enabled
        and start == current.dhcp_start
        and end == current.dhcp_end
        and lease == str(current.raw.get("leaseTime", ""))
    ):
        invalid("nothing to change")
    ip_class = 0 if mask.startswith("255.255.255.") else 1 if mask.startswith("255.255.") else 2
    letter, first, last = _CLASS_HOST_RANGES[ip_class]
    if ip_cmp(ip, first) == -1 or ip_cmp(ip, last) == 1:
        invalid(f"the LAN IP address must be a class {letter} address")
    if ip_class == 2 and int(ip.split(".", maxsplit=1)[0]) == 127:
        invalid("the LAN IP address is invalid")
    octets = [int(o) for o in mask.split(".")]
    if ip_class == 0 and octets[3] in (254, 255):
        invalid("the subnet mask must be 255.255.255.x")
    if ip_class == 1 and octets[3] != 0:
        invalid("the subnet mask must be 255.255.x.0")
    if ip_class == 2 and (not mask.startswith("255.") or octets[2] != 0 or octets[3] != 0):
        invalid("the subnet mask must be 255.x.0.0")
    if not _host_in_subnet(ip, mask, ip_class):
        invalid("the LAN IP address is invalid for this subnet mask")
    bounds = network_range(ip, mask, ip_class)
    assert bounds is not None  # checked by _host_in_subnet
    network, broadcast = bounds
    if ip_class == 0 and current.operation_mode in ("Bridge", "Eogre"):
        start, end = _bridge_dhcp_range(ip, start, end)
    if dhcp_enabled:
        if not is_ipv4(start):
            invalid("the DHCP start address is invalid")
        if not is_ipv4(end):
            invalid("the DHCP end address is invalid")
        if ip_cmp(start, end) == 1:
            invalid("the DHCP start address is after the end address")
        if (ip_cmp(ip, start) == 1 and ip_cmp(ip, end) == -1) or ip in (start, end):
            if start == network:
                invalid("the DHCP range starts at the network address")
            if end == broadcast:
                invalid("the DHCP range ends at the broadcast address")
            invalid("the LAN IP address is inside the DHCP range")
        if not (ip_cmp(start, network) == 1 and ip_cmp(start, broadcast) == -1):
            invalid("the DHCP start address is outside the subnet")
        if not (ip_cmp(end, network) == 1 and ip_cmp(end, broadcast) == -1):
            invalid("the DHCP end address is outside the subnet")
        lease_value = _js_parse_int(lease)
        if lease_value is None or not MIN_LEASE_TIME <= lease_value <= MAX_LEASE_TIME:
            invalid(f"the lease time must be {MIN_LEASE_TIME}-{MAX_LEASE_TIME} minutes")
    return {
        "ipClass": str(ip_class),
        "subnetMaskClass": str(ip_class),
        "hostIP": ip,
        "subnetMask": mask,
        "leaseTime": lease,
        "startIP": start,
        "endIP": end,
        "dhcp_enable": dhcp_enabled,
    }


def _js_parse_int(value: str) -> int | None:
    """JavaScript ``parseInt(value)``: leading integer, ``None`` for NaN."""
    match = re.match(r"\s*([-+]?\d+)", value)
    return int(match.group(1)) if match else None


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

    @uses(Page.LAN_SETTINGS, Endpoint.LAN_SAVE)
    async def update_settings(
        self,
        *,
        ip: str | None = None,
        subnet_mask: str | None = None,
        dhcp_enabled: bool | None = None,
        dhcp_start: str | None = None,
        dhcp_end: str | None = None,
        lease_time: int | None = None,
        confirm: bool = False,
    ) -> None:
        """Change the LAN address and the DHCP server. Destructive: ``confirm=True``.

        Omitted fields keep their current value; the UI's checks run first
        (``internetProtoSave``). The router restarts its LAN, which drops every
        LAN connection (and, after an address change, the router moves): the
        session is forgotten and a dropped connection is not an error.
        """
        current = await self.get_settings()
        fields = _lan_save_body(
            current,
            ip=(current.ip or "") if ip is None else ip,
            mask=(current.subnet_mask or "") if subnet_mask is None else subnet_mask,
            dhcp_enabled=current.dhcp_enabled if dhcp_enabled is None else dhcp_enabled,
            start=(current.dhcp_start or "") if dhcp_start is None else dhcp_start,
            end=(current.dhcp_end or "") if dhcp_end is None else dhcp_end,
            lease=(
                str(current.raw.get("leaseTime", "")) if lease_time is None else str(lease_time)
            ),
        )

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, **fields}

        data = await self._client._call(
            Endpoint.LAN_SAVE, body, confirmed=confirm, tolerate_disconnect=True
        )
        if data.get("result") is False:
            raise Id525CommandError(Endpoint.LAN_SAVE, data.get("error"))
        self._client._forget_session()

    @uses(Endpoint.ETH_WAN)
    async def set_ethernet_port_role(
        self, role: EthernetPortRole, *, confirm: bool = False
    ) -> None:
        """Use the configurable Ethernet port as WAN or LAN. Destructive: ``confirm=True``.

        The router applies it after a reboot. A dropped connection is
        tolerated (and then the session is forgotten).
        """

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "ethWanEnabled": 1 if EthernetPortRole(role) is EthernetPortRole.WAN else 0,
            }

        data = await self._client._call(
            Endpoint.ETH_WAN, body, confirmed=confirm, tolerate_disconnect=True
        )
        if not data:
            self._client._forget_session()
        elif data.get("result") is False:
            raise Id525CommandError(Endpoint.ETH_WAN, data.get("error"))
