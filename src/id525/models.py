"""Typed data models returned by the ID525 client."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date, datetime, timedelta


class LoginState(IntEnum):
    """Value of ``login`` returned by ``login_query.cgi``."""

    UNKNOWN = -1
    NOT_LOGGED_IN = 0
    LOGGED_IN = 1
    EXPIRED = 2
    KICKED = 3
    EXPIRING = 6

    @classmethod
    def _missing_(cls, value: object) -> Self:
        return cls.UNKNOWN


class SimState(StrEnum):
    """SIM / cellular registration state (``sim_card_state``)."""

    UNKNOWN = "Unknown"
    NO_SIM = "No SIM"
    INSERTED = "Inserted"
    INVALID_SIM = "Invalid SIM"
    ENTER_PIN = "Enter PIN"
    PIN_LOCKED = "PIN Locked"
    PUK_LOCKED = "PUK Locked"
    SIM_LOCKED = "SIM Locked"
    CONNECTED = "Connected"
    CONNECTED_ROAMING = "Connected (Roaming)"

    @classmethod
    def _missing_(cls, value: object) -> Self:
        # The web UI matches "Invalid SIM" with indexOf: suffixed variants exist.
        if isinstance(value, str) and value.startswith(cls.INVALID_SIM.value):
            return cls.INVALID_SIM
        return cls.UNKNOWN


class ClientInterface(StrEnum):
    """Interface a LAN client is attached to."""

    ETHERNET = "Ethernet"
    WIFI_2G = "WiFi 2.4G"
    WIFI_5G = "WiFi 5G"
    UNKNOWN = "Unknown"

    @classmethod
    def _missing_(cls, value: object) -> Self:
        return cls.UNKNOWN


def _raw() -> Any:
    """Field holding the raw payload (excluded from repr/eq)."""
    return field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class IpConfig:
    """WAN IP configuration for one address family."""

    address: str | None
    gateway: str | None
    dns: tuple[str, ...]
    netmask: str | None = None
    prefix: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class NetworkStatus:
    """Main status dashboard (``net_status_retrieve.cgi``)."""

    sim_state: SimState
    signal_level: int | None
    """Signal bars 0-4 as computed by the router."""
    operation_mode: str
    """Radio technology and operator, e.g. ``"5G I TIM"``."""
    plmn: str
    connection_duration: timedelta | None
    data_sent_gb: float | None
    data_received_gb: float | None
    statistics_duration: timedelta | None
    """Time elapsed since the data counters were last reset."""
    statistics_reset_date: date | None
    ipv4: IpConfig
    ipv6: IpConfig
    lan_ip: str | None
    wifi_enabled: bool
    ssid_2g: str | None
    ssid_5g: str | None
    wifi_clients_2g: int
    wifi_clients_5g: int
    usb_clients: int
    ethernet_link_speeds: tuple[int | None, ...]
    """Link speed in Mbit/s per Ethernet port (``None`` if down/unknown)."""
    fqdn: str | None
    raw: Mapping[str, Any] = _raw()

    @property
    def is_connected(self) -> bool:
        """Return True if the router is registered on the cellular network."""
        return self.sim_state in (SimState.CONNECTED, SimState.CONNECTED_ROAMING)

    @property
    def is_roaming(self) -> bool:
        """Return True if the router is roaming."""
        return self.sim_state is SimState.CONNECTED_ROAMING


@dataclass(frozen=True, slots=True, kw_only=True)
class ConnectedClient:
    """A device in the router's LAN client list."""

    mac: str
    ip: str | None
    hostname: str | None
    interface: ClientInterface
    interface_raw: str
    raw: Mapping[str, Any] = _raw()


@dataclass(frozen=True, slots=True, kw_only=True)
class Cell:
    """A serving cell (LTE or NR)."""

    cell_type: str
    """``PCell`` or ``SCell``."""
    network_type: str
    """``4G`` or ``5G``."""
    cell_id: int | None
    """ECI (LTE) / NCI (NR). The firmware may report the LTE ECI for NR cells too."""
    pci: int | None
    band: str
    bandwidth_mhz: float | None
    arfcn: int | None
    rsrp: float | None
    """dBm."""
    rsrq: float | None
    """dB."""
    snr: float | None
    """dB."""
    raw: Mapping[str, Any] = _raw()

    @property
    def is_primary(self) -> bool:
        """Return True for a primary cell."""
        return self.cell_type.lower() == "pcell"


@dataclass(frozen=True, slots=True, kw_only=True)
class CellularInfo:
    """Serving cells (``cellular-status`` page)."""

    cells: tuple[Cell, ...]

    def primary(self, network_type: str) -> Cell | None:
        """Return the primary cell of the given network type (``"4G"``/``"5G"``)."""
        return next(
            (c for c in self.cells if c.is_primary and c.network_type == network_type), None
        )

    @property
    def primary_5g(self) -> Cell | None:
        """Return the NR primary cell, if any."""
        return self.primary("5G")

    @property
    def primary_4g(self) -> Cell | None:
        """Return the LTE primary cell, if any."""
        return self.primary("4G")


@dataclass(frozen=True, slots=True, kw_only=True)
class RateStats:
    """Current / max / min of a measurement over the monitoring window."""

    current: float | None
    maximum: float | None
    minimum: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Utilization:
    """System utilisation (``util-status`` page)."""

    cpu_percent: RateStats
    memory_percent: RateStats
    uplink_bps: RateStats
    downlink_bps: RateStats
    monitoring_window: timedelta | None
    uptime: timedelta | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DeviceInfo:
    """Device identity (``help-about`` page)."""

    model: str
    serial_number: str | None
    hardware_version: str | None
    software_version: str | None
    imei: str | None
    imsi: str | None
    phone_number: str | None
    apns: tuple[str, ...]
    mac: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SmsMessage:
    """A message from the SMS store."""

    index: int
    phone_number: str
    text: str
    time_raw: str
    time: datetime | None
    read_status: int
    """0 unread inbound, 1 read inbound, >1 outbound (6 = delivered)."""

    @property
    def is_outbound(self) -> bool:
        """Return True for messages sent by the router."""
        return self.read_status > 1

    @property
    def is_unread(self) -> bool:
        """Return True for inbound messages not read yet."""
        return self.read_status == 0


@dataclass(frozen=True, slots=True, kw_only=True)
class SmsInbox:
    """The SMS store (``req_smsReload.cgi``)."""

    messages: tuple[SmsMessage, ...]
    update_marker: str
    """Opaque value that changes whenever the SMS store changes."""

    @property
    def unread_count(self) -> int:
        """Return the number of unread inbound messages."""
        return sum(1 for m in self.messages if m.is_unread)

    @property
    def inbound(self) -> tuple[SmsMessage, ...]:
        """Return inbound messages only."""
        return tuple(m for m in self.messages if not m.is_outbound)

    @property
    def latest(self) -> SmsMessage | None:
        """Return the most recent inbound message (by time, then index)."""
        inbound = self.inbound
        if not inbound:
            return None
        return max(
            inbound,
            key=lambda m: (m.time.timestamp() if m.time else float("-inf"), m.index),
        )
