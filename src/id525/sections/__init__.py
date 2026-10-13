"""Per-page API sections, attached to :class:`id525.Id525Client` as attributes."""

from .account import AccountApi
from .base import Section
from .cellular import CellularApi
from .ddns import DdnsApi
from .diagnostics import DiagnosticsApi
from .firewall import FirewallApi
from .ip_filter import IpFilterApi
from .lan import DhcpReservation, LanApi, LanSettings
from .mac_filter import MacFilterApi
from .port_forwarding import PortForwardingApi
from .sms import SmsApi
from .software import SoftwareApi
from .system import SystemApi
from .url_filter import UrlFilterApi
from .voip import VoipApi
from .wifi import WifiApi

SECTIONS: dict[str, type[Section]] = {
    "account": AccountApi,
    "cellular": CellularApi,
    "ddns": DdnsApi,
    "diagnostics": DiagnosticsApi,
    "firewall": FirewallApi,
    "ip_filter": IpFilterApi,
    "lan": LanApi,
    "mac_filter": MacFilterApi,
    "port_forwarding": PortForwardingApi,
    "sms": SmsApi,
    "software": SoftwareApi,
    "system": SystemApi,
    "url_filter": UrlFilterApi,
    "voip": VoipApi,
    "wifi": WifiApi,
}
"""Client attribute name -> section class."""

__all__ = [
    "SECTIONS",
    "AccountApi",
    "CellularApi",
    "DdnsApi",
    "DhcpReservation",
    "DiagnosticsApi",
    "FirewallApi",
    "IpFilterApi",
    "LanApi",
    "LanSettings",
    "MacFilterApi",
    "PortForwardingApi",
    "Section",
    "SmsApi",
    "SoftwareApi",
    "SystemApi",
    "UrlFilterApi",
    "VoipApi",
    "WifiApi",
]
