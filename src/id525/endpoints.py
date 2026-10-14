"""Registry of every router API endpoint and UI page, with safety metadata.

This module is the single source of truth for:

* what the client is allowed to call (:class:`Endpoint` is an allow-list:
  ``Id525Client`` refuses to POST anything else);
* how dangerous each call is (:class:`Kind`), which the client enforces
  centrally before any byte leaves the machine;
* how much we know about it (:class:`Status`), which drives the coverage map
  published in the README.

Every endpoint was found by static analysis of the router's web UI. ``ref``
points at the UI source line that calls it (firmware ``ID525_REL_1.0.09.17``).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from .const import API_PATH, PAGE_PATH

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class Kind(StrEnum):
    """What a call does to the router."""

    SESSION = "session"
    """Login / logout / CSRF-token plumbing."""
    READ = "read"
    """Returns data, changes nothing."""
    ACTION = "action"
    """Has side effects but changes no configuration (ping, scans, SMS send...)."""
    WRITE = "write"
    """Changes persistent configuration."""
    DESTRUCTIVE = "destructive"
    """Can cut off the controlling host or lose data (reboot, LAN / bridge /
    WAN-port changes, admin password, counter or APN resets...): every call
    needs ``confirm=True``."""

    @property
    def mutating(self) -> bool:
        """Return True if the call needs a client created with ``read_only=False``."""
        return self in (Kind.ACTION, Kind.WRITE, Kind.DESTRUCTIVE)


class Status(StrEnum):
    """How an endpoint is supported by this library, from most to least trusted."""

    LIVE_VERIFIED = "live-verified"
    """Implemented; behaviour observed on a real router (read-only probes, or a
    ``--trace`` of the call run by the user)."""
    UI_CAPTURED = "ui-captured"
    """Implemented; request bytes proven identical to the router's own web UI,
    captured offline by running the UI code against a local mock."""
    UI_CAPTURED_SYNTHETIC = "ui-captured-synthetic"
    """As ``ui-captured``, but starting from invented page data (the real dump
    had e.g. no table rows), so the types of existing entries are assumed."""
    STATIC = "static"
    """Implemented from reading the UI code only (no capture)."""
    PLANNED = "planned"
    """Not implemented yet."""
    STUB_UNSAFE = "stub-unsafe"
    """Deliberately not implemented: irreversible or can brick the device."""
    STUB_POLICY = "stub-policy"
    """Deliberately not implemented: SIM PIN / PUK (a wrong PUK locks the SIM)."""
    STUB_UNKNOWN = "stub-unknown"
    """Not implemented: semantics cannot be derived offline."""
    DEAD_CODE = "dead-code"
    """Only referenced by unreachable UI code; not implemented."""
    NO_DATA = "no-data"
    """(Pages only) the page embeds no data of its own, or only what an
    endpoint already returns: there is nothing to parse."""

    @property
    def implemented(self) -> bool:
        """Return True if the client may call the endpoint."""
        return self in (
            Status.LIVE_VERIFIED,
            Status.UI_CAPTURED,
            Status.UI_CAPTURED_SYNTHETIC,
            Status.STATIC,
        )


@dataclass(frozen=True, slots=True)
class EndpointInfo:
    """Metadata of one endpoint."""

    page: str
    """UI page that calls it (``common`` for the shared UI script)."""
    kind: Kind
    status: Status
    ref: str
    """UI source location of the call, ``file:line``."""
    summary: str


class Endpoint(StrEnum):
    """Every ``/cgi-bin/cgi/<name>.cgi`` endpoint the web UI calls."""

    # session plumbing, shared UI script
    TOKEN_QUERY = "token_query"
    LOGIN = "login_req"
    LOGOUT = "logout_req"
    LOGIN_QUERY = "login_query"
    # net-status
    NET_STATUS = "net_status_retrieve"
    PIN_ENTER = "pin_enter"
    PUK_ENTER = "puk_enter"
    DATA_STATUS = "data_status"
    # client-status
    CLIENT_STATUS = "client_status_retrieve"
    # adm-sms
    SMS_LIST = "req_smsReload"
    SMS_UPDATE_STATUS = "req_smsUpdateStatus"
    SMS_DELETE = "req_smsDelete"
    SMS_COMPOSE = "req_smsCompose"
    # adm-sw
    ACS_CHECK_UPDATE = "acs_check_update"
    ACS_CHECK_UPDATE_STATUS = "acs_check_update_status"
    ACS_UPDATE_CONFIRM = "acs_update_confirm"
    DO_UPGRADE = "do_upgrade"
    UPLOAD_FILE = "upload_file"
    # adm-backup
    REBOOT = "reboot"
    RESTORE_DEFAULT = "restore_default"
    BACKUP_CONFIG = "bkupConfig_apply"
    RESTORE_CONFIG = "restoreCofig_apply"
    # adm-user
    SET_ACCOUNT = "set_account_management"
    SET_DEVICE_MANAGEMENT = "set_device_management"
    RESET_DATA = "reset_data"
    DATA_USAGE_SAVE = "data_usage_save"
    BATTERY_APPLY = "battery_apply"
    SLEEP_MODE_SAVE = "sleepmode_save"
    RELOAD_PASSWORD = "reload_password"
    # cellular-settings
    CELLULAR_MODE = "req_CellularModeSelection"
    CHANGE_PIN = "req_ChangePIN"
    PIN_LOCK = "req_PINLockSave"
    ROAMING = "req_ChangeRoaming"
    OPERATION_MODE = "req_LanOperationModeSave"
    REGISTER_OPERATOR = "req_RegistingOperators"
    SEARCH_OPERATORS = "req_SearchOperators"
    APN_ADD = "req_addUserApn"
    APN_EDIT = "req_editUserApn"
    APN_DELETE = "req_deleteUserApn"
    APN_DEFAULT_SAVE = "req_defaultApnSave"
    APN_DEFAULT_RESET = "req_defaultApnReset"
    # lan-settings
    LAN_SAVE = "req_LanInternetProtoSave"
    ETH_WAN = "req_ethWanEnabled"
    DHCP_RESERVATION_ADD = "req_LanStaticAddrAdd"
    DHCP_RESERVATION_MODIFY = "req_LanStaticAddrModify"
    DHCP_RESERVATION_DELETE = "req_LanStaticAddrDelete"
    # wifi-settings
    WIFI_SETTING = "req_wifiSetting"
    WPS_SETTING = "req_wpsSetting"
    WPS_START = "req_wpsStartScan"
    WPS_CHECK = "req_wpsCheckScan"
    WPS_STOP = "req_wpsStopScan"
    MESH_SETTING = "req_meshRouterSetting"
    # voip-settings
    VOIP_APPLY = "voip_apply"
    # fw-adv
    FIREWALL_LEVEL = "fw_adv_apply"
    VPN_PASSTHROUGH = "fw_adv_vpn_apply"
    # fw-ddns
    DDNS_GET = "get_ddns_config"
    DDNS_SET = "set_ddns_config"
    # fw-ipfilter
    IPFILTER_ADD = "ipfilter_add"
    IPFILTER_EDIT = "ipfilter_edit"
    IPFILTER_SAVE = "ipfilter_save"
    # fw-macfilter
    MACFILTER_ADD = "macfilter_add"
    MACFILTER_EDIT = "macfilter_edit"
    MACFILTER_DELETE = "macfilter_delete"
    MACFILTER_SAVE = "macfilter_save"
    SET_HOST_NAME = "set_host_name"
    # fw-portfwd
    DMZ_SAVE = "dmz_save"
    PORTFWD_STATUS = "set_portforward_status"
    PORTFWD_ADD = "portforward_add"
    PORTFWD_EDIT = "portforward_edit"
    PORTFWD_DELETE = "portforward_delete"
    # fw-urlfilter
    URLFILTER_STATUS = "urlfilter_status_save"
    URLFILTER_ADD = "urlfilter_add_save"
    URLFILTER_EDIT = "urlfilter_edit"
    URLFILTER_DELETE = "urlfilter_delete_save"
    # self-diag / self-ping / self-tracert
    DIAG_CONNECTED = "req_DiagnosticConnectedTest"
    CPU_USAGE_TEST = "req_cpuUsageTest"
    PING = "req_pingTest"
    TRACEROUTE = "req_traceRouteTest"

    @property
    def path(self) -> str:
        """Return the URL path of the endpoint."""
        return API_PATH.format(self.value)

    @property
    def info(self) -> EndpointInfo:
        """Return the endpoint metadata."""
        return ENDPOINTS[self]


class Page(StrEnum):
    """Every UI page under ``/cgi-bin/cm/``."""

    NET_STATUS = "net-status"
    CELLULAR_STATUS = "cellular-status"
    CLIENT_STATUS = "client-status"
    UTILIZATION = "util-status"
    ABOUT = "help-about"
    ACCOUNT = "adm-user"
    SOFTWARE = "adm-sw"
    SMS = "adm-sms"
    BACKUP = "adm-backup"
    CELLULAR_SETTINGS = "cellular-settings"
    LAN_SETTINGS = "lan-settings"
    WIFI_SETTINGS = "wifi-settings"
    VOIP_SETTINGS = "voip-settings"
    FIREWALL = "fw-adv"
    DDNS = "fw-ddns"
    IP_FILTER = "fw-ipfilter"
    MAC_FILTER = "fw-macfilter"
    PORT_FORWARDING = "fw-portfwd"
    URL_FILTER = "fw-urlfilter"
    DIAGNOSTICS = "self-diag"
    PING = "self-ping"
    TRACEROUTE = "self-tracert"

    @property
    def path(self) -> str:
        """Return the URL path of the page."""
        return PAGE_PATH.format(self.value)

    @property
    def info(self) -> PageInfo:
        """Return the page metadata."""
        return PAGES[self]


@dataclass(frozen=True, slots=True)
class PageInfo:
    """Metadata of one UI page: its title and how its embedded data is read."""

    title: str
    status: Status
    """Status of *parsing the page* (a plain authenticated GET, always a read)."""


_S, _R, _A, _W, _D = Kind.SESSION, Kind.READ, Kind.ACTION, Kind.WRITE, Kind.DESTRUCTIVE
_LIVE, _CAPT, _STATIC, _TODO = (
    Status.LIVE_VERIFIED,
    Status.UI_CAPTURED,
    Status.STATIC,
    Status.PLANNED,
)
_SYNTH = Status.UI_CAPTURED_SYNTHETIC
_UNSAFE, _POLICY, _UNKNOWN, _DEAD = (
    Status.STUB_UNSAFE,
    Status.STUB_POLICY,
    Status.STUB_UNKNOWN,
    Status.DEAD_CODE,
)
_E = Endpoint

ENDPOINTS: Final[dict[Endpoint, EndpointInfo]] = {
    _E.TOKEN_QUERY: EndpointInfo("common", _S, _LIVE, "scriptGeneric.js:117", "New CSRF token"),
    _E.LOGIN: EndpointInfo("common", _S, _LIVE, "login.html", "Log in"),
    _E.LOGOUT: EndpointInfo("common", _S, _LIVE, "scriptGeneric.js:92", "Log out"),
    _E.LOGIN_QUERY: EndpointInfo("common", _S, _LIVE, "scriptGeneric.js:146", "Session state"),
    _E.NET_STATUS: EndpointInfo("net-status", _R, _LIVE, "net-status.html:327", "Status"),
    _E.PIN_ENTER: EndpointInfo("net-status", _W, _POLICY, "net-status.html:275", "Enter PIN"),
    _E.PUK_ENTER: EndpointInfo("net-status", _W, _POLICY, "net-status.html:207", "Enter PUK"),
    _E.DATA_STATUS: EndpointInfo(
        "net-status", _W, _DEAD, "net-status.html:446", "Reset data counters (never called)"
    ),
    _E.CLIENT_STATUS: EndpointInfo(
        "client-status", _R, _LIVE, "client-status.html:157", "LAN clients"
    ),
    _E.SMS_LIST: EndpointInfo("adm-sms", _R, _LIVE, "adm-sms.html:610", "SMS list"),
    _E.SMS_UPDATE_STATUS: EndpointInfo(
        "adm-sms", _W, Status.UI_CAPTURED_SYNTHETIC, "adm-sms.html:453", "Mark SMS read"
    ),
    _E.SMS_DELETE: EndpointInfo(
        "adm-sms", _W, Status.UI_CAPTURED_SYNTHETIC, "adm-sms.html:658", "Delete SMS"
    ),
    _E.SMS_COMPOSE: EndpointInfo("adm-sms", _A, _CAPT, "adm-sms.html:702", "Send SMS"),
    _E.ACS_CHECK_UPDATE: EndpointInfo(
        "adm-sw", _A, _CAPT, "adm-sw.html:452", "Ask the operator for firmware (UI button disabled)"
    ),
    _E.ACS_CHECK_UPDATE_STATUS: EndpointInfo(
        "adm-sw", _A, _CAPT, "adm-sw.html:459", "Firmware check progress"
    ),
    _E.ACS_UPDATE_CONFIRM: EndpointInfo(
        "adm-sw", _D, _UNSAFE, "adm-sw.html:533", "Install operator firmware"
    ),
    _E.DO_UPGRADE: EndpointInfo("adm-sw", _D, _UNSAFE, "adm-sw.html:235", "Flash firmware"),
    _E.UPLOAD_FILE: EndpointInfo(
        "adm-sw", _D, _UNSAFE, "adm-sw.html:216", "Upload firmware / config file"
    ),
    _E.REBOOT: EndpointInfo("adm-backup", _D, _CAPT, "adm-backup.html:186", "Reboot"),
    _E.RESTORE_DEFAULT: EndpointInfo(
        "adm-backup", _D, _UNSAFE, "adm-backup.html:171", "Factory reset"
    ),
    _E.BACKUP_CONFIG: EndpointInfo(
        "adm-backup", _A, _UNKNOWN, "adm-backup.html:159", "Create config backup (hidden)"
    ),
    _E.RESTORE_CONFIG: EndpointInfo(
        "adm-backup", _D, _UNSAFE, "adm-backup.html:332", "Restore config backup"
    ),
    _E.SET_ACCOUNT: EndpointInfo(
        "adm-user", _D, _CAPT, "adm-user.html:440", "Change admin password"
    ),
    _E.SET_DEVICE_MANAGEMENT: EndpointInfo(
        "adm-user", _W, _CAPT, "adm-user.html:482", "Session timeout"
    ),
    _E.RESET_DATA: EndpointInfo("adm-user", _D, _CAPT, "adm-user.html:518", "Reset data usage"),
    _E.DATA_USAGE_SAVE: EndpointInfo(
        "adm-user", _W, _CAPT, "adm-user.html:541", "Data usage settings"
    ),
    _E.BATTERY_APPLY: EndpointInfo(
        "adm-user", _W, _DEAD, "adm-user.html:551", "Battery (never called)"
    ),
    _E.SLEEP_MODE_SAVE: EndpointInfo(
        "adm-user", _W, _DEAD, "adm-user.html:564", "Sleep mode (never called)"
    ),
    _E.RELOAD_PASSWORD: EndpointInfo(
        "adm-user", _R, _DEAD, "adm-user.html:261", "Admin password (never called)"
    ),
    _E.CELLULAR_MODE: EndpointInfo(
        "cellular-settings", _W, _CAPT, "cellular-settings.html:949", "Network mode"
    ),
    _E.CHANGE_PIN: EndpointInfo(
        "cellular-settings", _W, _POLICY, "cellular-settings.html:897", "Change PIN"
    ),
    _E.PIN_LOCK: EndpointInfo(
        "cellular-settings", _W, _POLICY, "cellular-settings.html:527", "PIN lock"
    ),
    _E.ROAMING: EndpointInfo(
        "cellular-settings", _W, _CAPT, "cellular-settings.html:863", "Roaming"
    ),
    _E.OPERATION_MODE: EndpointInfo(
        "cellular-settings", _D, _CAPT, "cellular-settings.html:996", "Router / bridge mode"
    ),
    _E.REGISTER_OPERATOR: EndpointInfo(
        "cellular-settings", _W, _CAPT, "cellular-settings.html:586", "Select operator"
    ),
    _E.SEARCH_OPERATORS: EndpointInfo(
        "cellular-settings", _A, _CAPT, "cellular-settings.html:840", "Scan operators"
    ),
    _E.APN_ADD: EndpointInfo(
        "cellular-settings", _W, _CAPT, "cellular-settings.html:1462", "Add APN"
    ),
    _E.APN_EDIT: EndpointInfo(
        "cellular-settings", _W, _CAPT, "cellular-settings.html:1610", "Edit APN"
    ),
    _E.APN_DELETE: EndpointInfo(
        "cellular-settings", _W, _CAPT, "cellular-settings.html:1650", "Delete APN"
    ),
    _E.APN_DEFAULT_SAVE: EndpointInfo(
        "cellular-settings", _W, _CAPT, "cellular-settings.html:467", "Select default APN"
    ),
    _E.APN_DEFAULT_RESET: EndpointInfo(
        "cellular-settings", _D, _DEAD, "cellular-settings.html:272", "Reset APNs (button unbound)"
    ),
    _E.LAN_SAVE: EndpointInfo("lan-settings", _D, _CAPT, "lan-settings.html:563", "LAN / DHCP"),
    _E.ETH_WAN: EndpointInfo(
        "lan-settings", _D, _CAPT, "lan-settings.html:600", "Ethernet WAN port"
    ),
    _E.DHCP_RESERVATION_ADD: EndpointInfo(
        "lan-settings", _W, _CAPT, "lan-settings.html:826", "Add DHCP reservation"
    ),
    _E.DHCP_RESERVATION_MODIFY: EndpointInfo(
        "lan-settings", _W, _CAPT, "lan-settings.html:677", "Edit DHCP reservation"
    ),
    _E.DHCP_RESERVATION_DELETE: EndpointInfo(
        "lan-settings", _W, _CAPT, "lan-settings.html:880", "Delete DHCP reservation"
    ),
    _E.WIFI_SETTING: EndpointInfo("wifi-settings", _W, _CAPT, "wifi-settings.html:1386", "Wi-Fi"),
    _E.WPS_SETTING: EndpointInfo("wifi-settings", _W, _CAPT, "wifi-settings.html:1432", "WPS"),
    _E.WPS_START: EndpointInfo("wifi-settings", _A, _CAPT, "wifi-settings.html:1462", "Start WPS"),
    _E.WPS_CHECK: EndpointInfo("wifi-settings", _A, _CAPT, "wifi-settings.html:1506", "WPS state"),
    _E.WPS_STOP: EndpointInfo("wifi-settings", _A, _CAPT, "wifi-settings.html:1530", "Stop WPS"),
    _E.MESH_SETTING: EndpointInfo(
        "wifi-settings", _W, _DEAD, "wifi-settings.html:1388", "Mesh (commented out)"
    ),
    _E.VOIP_APPLY: EndpointInfo("voip-settings", _W, _CAPT, "voip-settings.html:1", "VoIP / SIP"),
    _E.FIREWALL_LEVEL: EndpointInfo("fw-adv", _W, _CAPT, "fw-adv.html:137", "Firewall level"),
    _E.VPN_PASSTHROUGH: EndpointInfo("fw-adv", _W, _CAPT, "fw-adv.html:149", "VPN passthrough"),
    _E.DDNS_GET: EndpointInfo("fw-ddns", _R, _LIVE, "fw-ddns.html:68", "DDNS settings"),
    _E.DDNS_SET: EndpointInfo(
        "fw-ddns", _W, Status.UI_CAPTURED_SYNTHETIC, "fw-ddns.html:334", "Set DDNS"
    ),
    _E.IPFILTER_ADD: EndpointInfo("fw-ipfilter", _W, _CAPT, "fw-ipfilter.html:315", "Add IP rule"),
    _E.IPFILTER_EDIT: EndpointInfo(
        "fw-ipfilter", _W, Status.UI_CAPTURED_SYNTHETIC, "fw-ipfilter.html:490", "Edit IP rule"
    ),
    _E.IPFILTER_SAVE: EndpointInfo("fw-ipfilter", _W, _CAPT, "fw-ipfilter.html:511", "IP filter"),
    _E.MACFILTER_ADD: EndpointInfo("fw-macfilter", _W, _CAPT, "fw-macfilter.html:389", "Add MAC"),
    _E.MACFILTER_EDIT: EndpointInfo(
        "fw-macfilter", _W, Status.UI_CAPTURED_SYNTHETIC, "fw-macfilter.html:712", "Edit MAC"
    ),
    _E.MACFILTER_DELETE: EndpointInfo(
        "fw-macfilter", _W, Status.UI_CAPTURED_SYNTHETIC, "fw-macfilter.html:734", "Delete MAC"
    ),
    _E.MACFILTER_SAVE: EndpointInfo(
        "fw-macfilter", _W, _CAPT, "fw-macfilter.html:463", "MAC filter"
    ),
    _E.SET_HOST_NAME: EndpointInfo(
        "fw-macfilter", _W, _DEAD, "fw-macfilter.html:416", "Rename client (UI code broken)"
    ),
    _E.DMZ_SAVE: EndpointInfo("fw-portfwd", _W, _CAPT, "fw-portfwd.html:280", "DMZ"),
    _E.PORTFWD_STATUS: EndpointInfo(
        "fw-portfwd", _W, _CAPT, "fw-portfwd.html:295", "Port forwarding on/off"
    ),
    _E.PORTFWD_ADD: EndpointInfo("fw-portfwd", _W, _CAPT, "fw-portfwd.html:531", "Add forward"),
    _E.PORTFWD_EDIT: EndpointInfo(
        "fw-portfwd", _W, Status.UI_CAPTURED_SYNTHETIC, "fw-portfwd.html:741", "Edit forward"
    ),
    _E.PORTFWD_DELETE: EndpointInfo(
        "fw-portfwd", _W, Status.UI_CAPTURED_SYNTHETIC, "fw-portfwd.html:1036", "Delete forward"
    ),
    _E.URLFILTER_STATUS: EndpointInfo(
        "fw-urlfilter", _W, _CAPT, "fw-urlfilter.html:397", "URL filter on/off"
    ),
    _E.URLFILTER_ADD: EndpointInfo("fw-urlfilter", _W, _CAPT, "fw-urlfilter.html:477", "Add URL"),
    _E.URLFILTER_EDIT: EndpointInfo(
        "fw-urlfilter", _W, Status.UI_CAPTURED_SYNTHETIC, "fw-urlfilter.html:311", "Edit URL"
    ),
    _E.URLFILTER_DELETE: EndpointInfo(
        "fw-urlfilter", _W, Status.UI_CAPTURED_SYNTHETIC, "fw-urlfilter.html:520", "Delete URL"
    ),
    _E.DIAG_CONNECTED: EndpointInfo(
        "self-diag", _A, _CAPT, "self-diag.html:221", "Interfaces connected"
    ),
    _E.CPU_USAGE_TEST: EndpointInfo("self-diag", _A, _CAPT, "self-diag.html:276", "CPU usage"),
    _E.PING: EndpointInfo("self-ping", _A, _CAPT, "self-ping.html:166", "Ping"),
    _E.TRACEROUTE: EndpointInfo("self-tracert", _A, _CAPT, "self-tracert.html:182", "Traceroute"),
}

_P = Page

PAGES: Final[dict[Page, PageInfo]] = {
    # user trace, 2026-10-14; its SIM PIN vars may be blank
    _P.NET_STATUS: PageInfo("Network status", _LIVE),
    _P.CELLULAR_STATUS: PageInfo("Cellular status", _LIVE),
    _P.CLIENT_STATUS: PageInfo("Connected clients", Status.NO_DATA),  # = client_status_retrieve
    _P.UTILIZATION: PageInfo("Utilization", _LIVE),
    _P.ABOUT: PageInfo("About", _LIVE),
    _P.ACCOUNT: PageInfo("Account & data usage", _LIVE),  # user trace, 2026-10-14
    _P.SOFTWARE: PageInfo("Software update", _LIVE),  # user trace, 2026-10-14; all fields empty
    _P.SMS: PageInfo("SMS", Status.NO_DATA),  # messages come from req_smsReload
    _P.BACKUP: PageInfo("Backup & reboot", Status.NO_DATA),  # only a UI feature flag
    _P.CELLULAR_SETTINGS: PageInfo("Cellular settings", _LIVE),  # user trace, 2026-10-14
    _P.LAN_SETTINGS: PageInfo("LAN settings", _LIVE),  # user trace, 2026-10-14
    _P.WIFI_SETTINGS: PageInfo("Wi-Fi settings", _LIVE),  # user trace, 2026-10-14
    _P.VOIP_SETTINGS: PageInfo("VoIP settings", _LIVE),  # user trace, 2026-10-14
    _P.FIREWALL: PageInfo("Firewall", _LIVE),  # user trace, 2026-10-14
    _P.DDNS: PageInfo("Dynamic DNS", _LIVE),  # user trace, 2026-10-14
    _P.IP_FILTER: PageInfo("IP filter", _LIVE),  # user trace, 2026-10-14; no rules
    _P.MAC_FILTER: PageInfo("MAC filter", _LIVE),  # user trace, 2026-10-14; no rules
    _P.PORT_FORWARDING: PageInfo("Port forwarding & DMZ", _LIVE),  # 2026-10-14; no rules
    _P.URL_FILTER: PageInfo("URL filter", _LIVE),  # user trace, 2026-10-14; no rules
    _P.DIAGNOSTICS: PageInfo("Self diagnostics", _STATIC),
    _P.PING: PageInfo("Ping", _LIVE),  # user trace, 2026-10-14
    _P.TRACEROUTE: PageInfo("Traceroute", _STATIC),
}


def uses[**P, R](
    *targets: Endpoint | Page,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Declare (and enforce) the endpoints / pages a client method calls.

    Before the method runs, every endpoint it declares is checked against the
    safety model (read-only client, ``confirm=True`` for destructive calls,
    unsupported endpoints), so a refused call sends nothing at all, not even a
    login. The declaration also feeds the coverage tests and the CLI.
    """

    def mark(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(func)
        async def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
            owner = args[0]
            client = getattr(owner, "_client", owner)
            confirmed = kwargs.get("confirm") is True
            for target in targets:
                if isinstance(target, Endpoint):
                    client.check_allowed(target, confirmed=confirmed)  # type: ignore[attr-defined]
            return await func(*args, **kwargs)

        guarded.__id525_uses__ = targets  # type: ignore[attr-defined]
        return guarded

    return mark
