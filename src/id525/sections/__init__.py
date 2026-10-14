"""Per-page API sections, attached to :class:`id525.Id525Client` as attributes."""

from .account import AccountApi, AccountSettings, DataUnit
from .base import Section
from .cellular import (
    Apn,
    ApnAuth,
    ApnIpType,
    CellularApi,
    CellularSettings,
    NetworkMode,
    OperationMode,
    Operator,
)
from .ddns import DdnsApi, DdnsSettings
from .diagnostics import (
    ConnectivityCheck,
    DiagnosticsApi,
    PingDefaults,
    PingReport,
    SelfTestReport,
    TracerouteReport,
)
from .firewall import FirewallApi, FirewallLevel, FirewallSettings
from .ip_filter import FilterMode, IpFilterApi, IpFilterRule, IpFilterSettings, IpType
from .lan import DhcpReservation, EthernetPortRole, LanApi, LanSettings
from .mac_filter import MacFilterApi, MacFilterMode, MacFilterRule, MacFilterSettings
from .port_forwarding import (
    PortForwardingApi,
    PortForwardingSettings,
    PortForwardProtocol,
    PortForwardRule,
)
from .sms import SmsApi
from .software import SoftwareApi, SoftwareInfo
from .status import SimPinStatus, StatusApi
from .system import SystemApi
from .url_filter import UrlFilterApi, UrlFilterRule, UrlFilterSettings
from .voip import RegistrationStatus, VoipApi, VoipApn, VoipSettings
from .wifi import (
    WifiApi,
    WifiBand,
    WifiBandwidth,
    WifiInterface,
    WifiMode,
    WifiNetwork,
    WifiRadio,
    WifiSecurity,
    WifiSettings,
    WpsResult,
)

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
    "status": StatusApi,
    "system": SystemApi,
    "url_filter": UrlFilterApi,
    "voip": VoipApi,
    "wifi": WifiApi,
}
"""Client attribute name -> section class."""

__all__ = [
    "SECTIONS",
    "AccountApi",
    "AccountSettings",
    "Apn",
    "ApnAuth",
    "ApnIpType",
    "CellularApi",
    "CellularSettings",
    "ConnectivityCheck",
    "DataUnit",
    "DdnsApi",
    "DdnsSettings",
    "DhcpReservation",
    "DiagnosticsApi",
    "EthernetPortRole",
    "FilterMode",
    "FirewallApi",
    "FirewallLevel",
    "FirewallSettings",
    "IpFilterApi",
    "IpFilterRule",
    "IpFilterSettings",
    "IpType",
    "LanApi",
    "LanSettings",
    "MacFilterApi",
    "MacFilterMode",
    "MacFilterRule",
    "MacFilterSettings",
    "NetworkMode",
    "OperationMode",
    "Operator",
    "PingDefaults",
    "PingReport",
    "PortForwardProtocol",
    "PortForwardRule",
    "PortForwardingApi",
    "PortForwardingSettings",
    "RegistrationStatus",
    "Section",
    "SelfTestReport",
    "SimPinStatus",
    "SmsApi",
    "SoftwareApi",
    "SoftwareInfo",
    "StatusApi",
    "SystemApi",
    "TracerouteReport",
    "UrlFilterApi",
    "UrlFilterRule",
    "UrlFilterSettings",
    "VoipApi",
    "VoipApn",
    "VoipSettings",
    "WifiApi",
    "WifiBand",
    "WifiBandwidth",
    "WifiInterface",
    "WifiMode",
    "WifiNetwork",
    "WifiRadio",
    "WifiSecurity",
    "WifiSettings",
    "WpsResult",
]
