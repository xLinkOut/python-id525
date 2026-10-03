"""Pure parsing helpers: router payloads and UI pages -> typed models.

The router returns almost every value as a display string with units
(``"300.77 GB"``, ``"-79.0dBm"``, ``"37,10:55:44"``...). Parsers are lenient:
an unparsable value becomes ``None`` rather than an exception, because the
firmware is not documented and formats may drift between releases.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from .const import REDIRECT_PAGE_MARKERS
from .exceptions import Id525ResponseError
from .models import (
    Cell,
    CellularInfo,
    ClientInterface,
    ConnectedClient,
    DeviceInfo,
    IpConfig,
    NetworkStatus,
    RateStats,
    SimState,
    SmsInbox,
    SmsMessage,
    Utilization,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_DURATION_RE = re.compile(r"^\s*(\d+)\s*,\s*(\d+):(\d+):(\d+)\s*$")
_UNIT_DURATION_RE = re.compile(r"(\d+)\s*(day|hr|hour|min|sec)", re.IGNORECASE)
_QUANTITY_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$")
_JS_SETTER_RE = re.compile(
    r"(?:setInnerHtmlByValue|setInnerHtmlByClassName)\(\s*'(\w+)'\s*,\s*(['\"])(.*?)\2\s*\)"
)
_JS_VAR_RE = re.compile(r"\bvar\s+(\w+)\s*=\s*(['\"])(.*?)\2\s*;?")

_DATA_UNITS = {"B": 1024**-3, "KB": 1024**-2, "MB": 1024**-1, "GB": 1.0, "TB": 1024.0}
_RATE_UNITS = {"BPS": 1.0, "KBPS": 1e3, "MBPS": 1e6, "GBPS": 1e9}
_UNIT_SECONDS = {"day": 86400, "hr": 3600, "hour": 3600, "min": 60, "sec": 1}
_NOT_AVAILABLE = {"", "N/A", "NA", "-", "--"}
_SMS_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d,%H:%M:%S",
    "%y/%m/%d,%H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%d-%m-%Y %H:%M:%S",
)


def clean_str(value: Any) -> str | None:
    """Return a stripped string, or None for empty / "N/A"-like values."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text.upper() in _NOT_AVAILABLE else text


def parse_number(value: Any) -> float | None:
    """Extract the first number from a string like ``"-79.0dBm"``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    match = _NUMBER_RE.search(str(value or ""))
    return float(match.group()) if match else None


def parse_int(value: Any) -> int | None:
    """Parse an integer (``"163"``, ``163``), else None."""
    number = parse_number(value)
    return int(number) if number is not None and number.is_integer() else None


def parse_duration(value: Any) -> timedelta | None:
    """Parse the ``"D,HH:MM:SS"`` format used by the status page."""
    match = _DURATION_RE.match(str(value or ""))
    if not match:
        return None
    days, hours, minutes, seconds = (int(g) for g in match.groups())
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


def parse_unit_duration(value: Any) -> timedelta | None:
    """Parse ``"47 day(s), 01 Hr, 33 Min, 13 Sec."`` or ``"30 second(s)"``."""
    matches = _UNIT_DURATION_RE.findall(str(value or ""))
    if not matches:
        return None
    seconds = sum(int(n) * _UNIT_SECONDS[unit.lower()] for n, unit in matches)
    return timedelta(seconds=seconds)


def parse_data_gb(value: Any) -> float | None:
    """Parse a data volume (``"300.77 GB"``) and normalise it to GB (1024 base)."""
    match = _QUANTITY_RE.match(str(value or ""))
    if not match:
        return None
    factor = _DATA_UNITS.get(match.group(2).upper() or "GB")
    return None if factor is None else float(match.group(1)) * factor


def parse_rate_bps(value: Any) -> float | None:
    """Parse a data rate (``"17 Kbps"``, ``"436.89 Mbps"``) into bit/s."""
    match = _QUANTITY_RE.match(str(value or ""))
    if not match:
        return None
    factor = _RATE_UNITS.get(match.group(2).upper())
    return None if factor is None else float(match.group(1)) * factor


def parse_reset_date(value: Any) -> date | None:
    """Parse ``YYYY-MM-DD``; the router uses a 1980 date for "never reset"."""
    text = clean_str(value)
    if text is None or "1980" in text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_sms_time(value: Any) -> datetime | None:
    """Best-effort parse of an SMS timestamp (format not documented)."""
    text = clean_str(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in _SMS_TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)  # noqa: DTZ007 - router local time
        except ValueError:
            continue
    return None


def split_list(value: Any) -> tuple[str, ...]:
    """Split ``"a, b c"`` into ``("a", "b", "c")``."""
    return tuple(part for part in re.split(r"[,\s]+", str(value or "")) if part)


def uri_decode(value: Any) -> str | None:
    """Undo the URI encoding the UI reverses with ``decodeURIComponent``."""
    text = clean_str(value)
    return unquote(text) if text is not None else None


def is_redirect_page(html: str) -> bool:
    """Return True if the router served its "not logged in" redirect page."""
    return len(html) < 2048 and any(marker in html for marker in REDIRECT_PAGE_MARKERS)


def extract_entity_json(html: str, var_name: str) -> Any:
    """Extract a ``var x = '{ &quot;...&quot; }'`` JSON blob embedded in a page."""
    match = re.search(rf"\bvar\s+{re.escape(var_name)}\s*=\s*'(.*?)'\s*;?\s*$", html, re.M)
    if not match:
        msg = f"embedded variable {var_name!r} not found in page"
        raise Id525ResponseError(msg)
    try:
        return json.loads(match.group(1).replace("&quot;", '"'))
    except json.JSONDecodeError as err:
        msg = f"embedded variable {var_name!r} is not valid JSON"
        raise Id525ResponseError(msg) from err


def extract_js_values(html: str) -> dict[str, str]:
    """Collect server-substituted literals (``var x = '...'`` and UI setter calls)."""
    values = {m.group(1): m.group(3) for m in _JS_VAR_RE.finditer(html)}
    values.update({m.group(1): m.group(3) for m in _JS_SETTER_RE.finditer(html)})
    return values


def parse_network_status(data: Mapping[str, Any]) -> NetworkStatus:
    """Parse ``net_status_retrieve.cgi`` / the ``net_info`` page variable."""
    speeds = tuple(
        parse_int(data[key]) for key in sorted(k for k in data if re.fullmatch(r"speed_eth\d+", k))
    )
    return NetworkStatus(
        sim_state=SimState(str(data.get("sim_card_state", ""))),
        signal_level=parse_int(data.get("signalLevel")),
        operation_mode=str(data.get("operation_mode", "")).strip(),
        plmn=str(data.get("plmn", "")).strip(),
        connection_duration=parse_duration(data.get("connection_time")),
        data_sent_gb=parse_data_gb(data.get("data_tx")),
        data_received_gb=parse_data_gb(data.get("data_rx")),
        statistics_duration=parse_duration(data.get("duration_from_last_reset")),
        statistics_reset_date=parse_reset_date(data.get("statistic_reset_day")),
        ipv4=IpConfig(
            address=clean_str(data.get("ipv4_addr")),
            netmask=clean_str(data.get("ipv4_mask")),
            gateway=clean_str(data.get("ipv4_gw")),
            dns=split_list(data.get("ipv4_dns")),
        ),
        ipv6=IpConfig(
            address=clean_str(data.get("ipv6_addr")),
            prefix=clean_str(data.get("ipv6_prefix")),
            gateway=clean_str(data.get("ipv6_gw")),
            dns=split_list(data.get("ipv6_dns")),
        ),
        lan_ip=clean_str(data.get("hostIPAddr")),
        wifi_enabled=data.get("wifiStatus") is True,
        ssid_2g=uri_decode(data.get("ssid_2g")),
        ssid_5g=uri_decode(data.get("ssid_5g")),
        wifi_clients_2g=parse_int(data.get("clientNum_2g")) or 0,
        wifi_clients_5g=parse_int(data.get("clientNum_5g")) or 0,
        usb_clients=parse_int(data.get("clientNum_usb")) or 0,
        ethernet_link_speeds=speeds,
        fqdn=clean_str(data.get("fqdn")),
        raw=dict(data),
    )


def parse_clients(data: Mapping[str, Any]) -> tuple[ConnectedClient, ...]:
    """Parse ``client_status_retrieve.cgi`` / the ``clients_info`` page variable."""
    clients = []
    for item in data.get("client_list") or ():
        interface_raw = str(item.get("intf", "")).strip()
        clients.append(
            ConnectedClient(
                mac=str(item.get("mac", "")).strip().lower(),
                ip=clean_str(item.get("ip")),
                hostname=clean_str(item.get("hostName")),
                interface=ClientInterface(interface_raw),
                interface_raw=interface_raw,
                raw=dict(item),
            )
        )
    return tuple(clients)


def parse_cellular_page(html: str) -> CellularInfo:
    """Parse the ``cellular-status`` page (``cellInfo`` variable)."""
    payload = extract_entity_json(html, "cellInfo")
    cells = tuple(
        Cell(
            cell_type=str(item.get("cellType", "")).strip(),
            network_type=str(item.get("networkType", "")).strip(),
            cell_id=parse_int(item.get("eci")),
            pci=parse_int(item.get("pci")),
            band=str(item.get("band", "")).strip(),
            bandwidth_mhz=parse_number(item.get("bandwidth")),
            arfcn=parse_int(item.get("earfcn")),
            rsrp=parse_number(item.get("rsrp")),
            rsrq=parse_number(item.get("rsrq")),
            snr=parse_number(item.get("snr")),
            raw=dict(item),
        )
        for item in payload.get("cellList") or ()
    )
    return CellularInfo(cells=cells)


def _stats(values: Mapping[str, str], cur: str, mx: str, mn: str, parser: Any) -> RateStats:
    return RateStats(
        current=parser(values.get(cur)),
        maximum=parser(values.get(mx)),
        minimum=parser(values.get(mn)),
    )


def parse_utilization_page(html: str) -> Utilization:
    """Parse the ``util-status`` page (server-substituted literals)."""
    v = extract_js_values(html)
    if "currCpuUsage" not in v:
        msg = "utilisation values not found in page"
        raise Id525ResponseError(msg)
    return Utilization(
        cpu_percent=_stats(v, "currCpuUsage", "maxCpuUsage", "minCpuUsage", parse_number),
        memory_percent=_stats(v, "currMemUsage", "maxMemUsage", "minMemUsage", parse_number),
        uplink_bps=_stats(v, "upAvgDataRate", "upMaxDataRate", "upMinDataRate", parse_rate_bps),
        downlink_bps=_stats(
            v, "downAvgDataRate", "downMaxDataRate", "downMinDataRate", parse_rate_bps
        ),
        monitoring_window=parse_unit_duration(v.get("sysMonitoringDuration")),
        uptime=parse_unit_duration(v.get("devUptime")),
    )


def parse_about_page(html: str) -> DeviceInfo:
    """Parse the ``help-about`` page (server-substituted literals)."""
    v = extract_js_values(html)
    if "model_name" not in v and "imei" not in v:
        msg = "device information not found in page"
        raise Id525ResponseError(msg)
    apns = tuple(a.strip() for a in v.get("curApn", "").split(",") if a.strip())
    mac = clean_str(v.get("routerMac"))
    return DeviceInfo(
        model=v.get("model_name", "ID525"),
        serial_number=clean_str(v.get("serialNum")),
        hardware_version=clean_str(v.get("hwVer")),
        software_version=clean_str(v.get("swVer")),
        imei=clean_str(v.get("imei")),
        imsi=clean_str(v.get("imsi")),
        phone_number=clean_str(v.get("phoneNum")),
        apns=apns,
        mac=mac.lower() if mac else None,
    )


def parse_sms(data: Mapping[str, Any]) -> SmsInbox:
    """Parse ``req_smsReload.cgi``."""
    messages = tuple(
        SmsMessage(
            index=parse_int(item.get("index")) or 0,
            phone_number=str(item.get("phone_number", "")).strip(),
            text=str(item.get("context", "")),
            time_raw=str(item.get("time", "")),
            time=parse_sms_time(item.get("time")),
            read_status=parse_int(item.get("read_status")) or 0,
        )
        for item in data.get("message") or ()
    )
    return SmsInbox(messages=messages, update_marker=str(data.get("sms_update_time", "")))
