"""Cellular settings (``cellular-settings`` page) and SIM PIN handling."""

from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, NoReturn
from urllib.parse import unquote

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, Page, uses
from ..exceptions import Id525CommandError, Id525ResponseError
from ..models import _raw
from ..parsers import clean_str, extract_js_values, parse_int
from .base import Section, invalid

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_APNS = 5
"""The UI refuses to add an APN when 5 profiles (default included) exist."""
MAX_APN_LENGTH = 32
MAX_PROFILE_NAME_LENGTH = 32
_APN_RE = re.compile(r"^([a-zA-Z0-9]+\.){0,3}[a-zA-Z0-9]{1,}$")  # UI validateCommonAPN
_BAD_PERCENT_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_NUMERIC_VAR_RE = re.compile(r"\bvar\s+(\w+)\s*=\s*(-?\d+)\s*;")
_APN_VARS = ("defaultApnInfo", "user1ApnInfo", "user2ApnInfo", "user3ApnInfo", "user4ApnInfo")
_NO_SIM_STATES = ("SIM Locked", "No SIM")
_NO_NETWORKS = "No Avaiable Networks"  # sic, as compared by the UI


class NetworkMode(StrEnum):
    """Radio access modes offered by the UI (``mode_list_str``)."""

    AUTO = "4G/5G(Auto)"
    LTE = "4G"
    NR_SA = "5G SA"


_MODE_CODES = {NetworkMode.AUTO: "80", NetworkMode.LTE: "16", NetworkMode.NR_SA: "64"}


class OperationMode(StrEnum):
    """Router (NAT) or bridge (IP pass-through) operation."""

    ROUTING = "Routing"
    BRIDGE = "Bridge"


class ApnAuth(StrEnum):
    """APN authentication method."""

    NONE = "NONE"
    PAP = "PAP"
    CHAP = "CHAP"
    PAPCHAP = "PAPCHAP"


class ApnIpType(StrEnum):
    """APN PDP type (``IPType`` 0 / 1 / 2 on the wire)."""

    IPV4 = "ipv4"
    IPV6 = "ipv6"
    IPV4V6 = "ipv4v6"


_IP_TYPE_CODES = {ApnIpType.IPV4: 0, ApnIpType.IPV6: 1, ApnIpType.IPV4V6: 2}


@dataclass(frozen=True, slots=True, kw_only=True)
class Apn:
    """An APN profile (``defaultApnInfo`` / ``userNApnInfo``)."""

    instance: int
    """Router-side id of the profile."""
    profile_handle: int | None
    profile_name: str
    apn: str
    ip_type: ApnIpType
    auth: str
    username: str
    password: str
    enabled: bool
    active: bool
    is_default: bool
    raw: Mapping[str, Any] = _raw()


@dataclass(frozen=True, slots=True, kw_only=True)
class CellularSettings:
    """Cellular configuration as shown by the ``cellular-settings`` page."""

    network_mode: str | None
    available_modes: tuple[str, ...]
    scan_mode: str | None
    """``Automatic`` or ``Manual`` (UI-only: manual shows the operator scan)."""
    bridge_mode: bool
    model: str | None
    sim_state: str | None
    pin_enabled: bool
    pin_retries: int | None
    roaming: bool
    apns: tuple[Apn, ...]
    """All profiles, the default one first (it cannot be edited or deleted)."""
    raw: Mapping[str, Any] = _raw()

    @property
    def default_apn(self) -> Apn | None:
        """Return the default APN profile."""
        return next((a for a in self.apns if a.is_default), None)


@dataclass(frozen=True, slots=True, kw_only=True)
class Operator:
    """A network found by an operator scan (``scan_network`` entry)."""

    mcc: str
    mnc: str
    """As sent by the router (the UI zero-pads it only for display)."""
    name: str
    status: int
    network_type: str
    """``5`` 3G, ``8`` 4G, ``12`` 5G (as sent by the router)."""
    mnc_includes_pcs_digit: str
    state: str
    """``Current Serving``, ``Available``, ``Forbidden`` or ``Unknown``."""


def js_length(value: str) -> int:
    """JavaScript ``String.length`` (UTF-16 code units)."""
    return len(value.encode("utf-16-le")) // 2


def decode_uri_component(value: str) -> str:
    """JavaScript ``decodeURIComponent``: malformed input is an error, not ignored."""
    if _BAD_PERCENT_RE.search(value):
        invalid(f"malformed percent-encoding in {value!r}")
    try:
        return unquote(value, errors="strict")
    except UnicodeDecodeError:
        invalid(f"malformed percent-encoding in {value!r}")


def is_valid_apn(value: str) -> bool:
    """UI ``validateCommonAPN``: up to four dot-separated alphanumeric labels."""
    return bool(_APN_RE.match(value))


def _ip_type(code: Any) -> ApnIpType:
    """Loose mapping (``IPType == 0``), as for the default profile."""
    value = parse_int(code)
    if value == 0:
        return ApnIpType.IPV4
    return ApnIpType.IPV6 if value == 1 else ApnIpType.IPV4V6


def _strict_ip_type(code: Any) -> ApnIpType:
    """Strict mapping, as the edit dialog's ``switch`` (``"0"`` is not ``0``)."""
    if isinstance(code, int) and not isinstance(code, bool) and code in (0, 1):
        return ApnIpType.IPV4 if code == 0 else ApnIpType.IPV6
    return ApnIpType.IPV4V6


def _apn_json(html: str, var: str) -> dict[str, Any] | None:
    match = re.search(rf"\bvar\s+{var}\s*=\s*'(.*?)'\s*;", html)
    if match is None or len(match.group(1)) <= 2:  # the UI skips '{}'
        return None
    try:
        data = json.loads(html_lib.unescape(match.group(1)))
    except json.JSONDecodeError as err:
        msg = f"embedded variable {var!r} is not valid JSON"
        raise Id525ResponseError(msg) from err
    return data if isinstance(data, dict) else None


def _safe_decode(value: Any) -> str:
    text = str(value or "")
    return unquote(text) if not _BAD_PERCENT_RE.search(text) else text


def parse_cellular_page(html: str) -> CellularSettings:
    """Parse the data the router embeds in ``cellular-settings.html``."""
    values = extract_js_values(html)
    numbers = {m.group(1): int(m.group(2)) for m in _NUMERIC_VAR_RE.finditer(html)}
    apns = []
    raws = {}
    for var in _APN_VARS:
        data = _apn_json(html, var)
        if data is None:
            continue
        raws[var] = data
        apns.append(
            Apn(
                instance=parse_int(data.get("instance")) or 0,
                profile_handle=parse_int(data.get("profile_handle")),
                profile_name=_safe_decode(data.get("name")),
                apn=_safe_decode(data.get("apn")),
                ip_type=_ip_type(data.get("IPType")),
                auth=str(data.get("auth") or "NONE"),
                username=_safe_decode(data.get("user")),
                password=_safe_decode(data.get("passwd")),
                enabled=parse_int(data.get("disable")) == 0,
                active=parse_int(data.get("active")) == 1,
                is_default=var == "defaultApnInfo",
                raw=data,
            )
        )
    modes = str(values.get("mode_list_str", "")).split(",")
    return CellularSettings(
        network_mode=clean_str(values.get("modeSelected")),
        available_modes=tuple(m for m in modes[:-1] if m),  # the UI drops the last ("END")
        scan_mode=clean_str(values.get("scanMode")),
        bridge_mode=values.get("bridge_mode") not in (None, "0"),
        model=clean_str(values.get("model")),
        sim_state=clean_str(values.get("sim_card_state")),
        pin_enabled=values.get("pin_setting") == "1",
        pin_retries=numbers.get("pin_retry_cnt"),
        roaming=values.get("roaming_status") == "1",
        apns=tuple(apns),
        raw={**values, **numbers, **raws},
    )


def _operator_state(status: int) -> str:
    """Port of the UI's status decoding (``insert_operators_data``)."""
    indicator = status & 48
    if indicator == 16:
        return "Forbidden"
    if indicator == 32:
        if status & 3 == 1:
            return "Current Serving" if status & 192 == 64 else "Available"
        if status & 3 == 2:
            return "Available"
    return "Unknown"


def parse_scan_result(scan_network: Any) -> tuple[Operator, ...]:
    """Parse ``scan_network`` (``mcc,mnc,status,name,type,pcs;...``) like the UI.

    The UI ignores the last ``;``-separated element (normally empty), and
    treats short answers and ``No Avaiable Networks`` as "nothing found".
    """
    text = str(scan_network or "")
    if len(text) <= 5 or text == _NO_NETWORKS:
        return ()
    operators = []
    for entry in text.split(";")[:-1]:
        fields = [*entry.split(","), "", "", "", "", "", ""][:6]
        status = parse_int(fields[2]) or 0
        operators.append(
            Operator(
                mcc=fields[0],
                mnc=fields[1],
                status=status,
                name=fields[3],
                network_type=fields[4],
                mnc_includes_pcs_digit=fields[5],
                state=_operator_state(status),
            )
        )
    return tuple(operators)


def _padded(mcc: str, mnc: str, pcs: str) -> tuple[str, str]:
    """Return MCC / MNC in the zero-padded form the UI displays."""
    mcc = mcc.zfill(3) if len(mcc) < 3 else mcc
    if len(mnc) == 1:
        mnc = "0" + mnc
    if pcs == "1" and len(mnc) == 2:
        mnc = "0" + mnc
    return mcc, mnc


def _user_apn(settings: CellularSettings, instance: int) -> Apn:
    apn = next((a for a in settings.apns if a.instance == instance), None)
    if apn is None:
        invalid(f"no APN profile with instance {instance}")
    if apn.is_default:
        invalid("the default APN profile cannot be edited or deleted from the list")
    return apn


def _require_sim(settings: CellularSettings) -> None:
    if settings.sim_state == "No SIM":
        invalid("no SIM card: the UI disables APN changes")


class CellularApi(Section):
    """Network mode, roaming, operator selection, APNs; SIM PIN (unsupported)."""

    @uses(Page.CELLULAR_SETTINGS)
    async def get_settings(self) -> CellularSettings:
        """Return network mode, roaming, bridge mode, SIM/PIN state and APN profiles."""
        return parse_cellular_page(await self._client._page(Page.CELLULAR_SETTINGS))

    @uses(Page.CELLULAR_SETTINGS, Endpoint.CELLULAR_MODE)
    async def set_network_mode(self, mode: NetworkMode) -> None:
        """Select the radio access mode (one of the modes the router offers)."""
        mode = NetworkMode(mode)
        current = await self.get_settings()
        if len(current.available_modes) < 2:
            invalid("the router offers a single network mode: the UI disables saving it")
        if mode.value not in current.available_modes:
            invalid(f"{mode.value!r} is not offered by this router: {current.available_modes}")

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "modeSelected": _MODE_CODES[mode]}

        await self._client._command(Endpoint.CELLULAR_MODE, body)

    async def _set_roaming(self, *, enabled: bool) -> None:
        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "roaming_status": 1 if enabled else 0}

        await self._client._command(Endpoint.ROAMING, body)

    @uses(Endpoint.ROAMING)
    async def enable_roaming(self) -> None:
        """Allow data roaming."""
        await self._set_roaming(enabled=True)

    @uses(Endpoint.ROAMING)
    async def disable_roaming(self) -> None:
        """Forbid data roaming."""
        await self._set_roaming(enabled=False)

    @uses(Page.CELLULAR_SETTINGS, Endpoint.OPERATION_MODE)
    async def set_operation_mode(self, mode: OperationMode, *, confirm: bool = False) -> None:
        """Switch between routing (NAT) and bridge mode. Destructive: needs ``confirm=True``.

        Changing it can cut off the host running this client, so a dropped
        connection is tolerated and the session is dropped afterwards.
        """
        mode = OperationMode(mode)
        current = await self.get_settings()
        if current.model == "MiFi" and mode is OperationMode.BRIDGE:
            invalid("bridge mode is not offered on this model")

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "modeSelectType": mode.value, "macSelectType": "Auto"}

        data = await self._client._call(
            Endpoint.OPERATION_MODE, body, confirmed=confirm, tolerate_disconnect=True
        )
        self._client._forget_session()
        if data.get("result") is False:
            raise Id525CommandError(Endpoint.OPERATION_MODE, data.get("error"))

    async def _scan(self) -> tuple[Operator, ...]:
        data = await self._client._call(Endpoint.SEARCH_OPERATORS)
        if data.get("result") is False:
            raise Id525CommandError(Endpoint.SEARCH_OPERATORS, data.get("error"))
        return parse_scan_result(data.get("scan_network"))

    @uses(Endpoint.SEARCH_OPERATORS)
    async def search_operators(self) -> tuple[Operator, ...]:
        """Scan for mobile networks (manual selection).

        Warning: the scan can take minutes and may disrupt the cellular link;
        the UI reloads the page after 60 s. Use a long ``request_timeout``.
        """
        return await self._scan()

    @uses(Page.CELLULAR_SETTINGS, Endpoint.SEARCH_OPERATORS, Endpoint.REGISTER_OPERATOR)
    async def register_operator(self, mcc: str, mnc: str) -> None:
        """Scan, then register on the network ``mcc``/``mnc`` (manual selection).

        Like the UI, only an ``Available`` network found by the scan can be
        chosen (not the current one, not a forbidden one). ``mnc`` may be given
        as sent by the router or zero-padded as the UI shows it.
        """
        current = await self.get_settings()
        if current.sim_state in _NO_SIM_STATES:
            invalid(f"cannot register with SIM state {current.sim_state!r}")
        found = await self._scan()
        operator = next(
            (
                o
                for o in found
                if (o.mcc, o.mnc) == (mcc, mnc)
                or _padded(o.mcc, o.mnc, o.mnc_includes_pcs_digit) == (mcc, mnc)
            ),
            None,
        )
        if operator is None:
            invalid(f"network {mcc}-{mnc} not found by the scan")
        if operator.state != "Available":
            invalid(f"network {mcc}-{mnc} is {operator.state}: the UI does not offer it")

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "mcc": operator.mcc,
                "mnc": operator.mnc,
                "type": operator.network_type,
                "mnc_includes_pcs_digit": operator.mnc_includes_pcs_digit,
            }

        await self._client._command(Endpoint.REGISTER_OPERATOR, body)

    @uses(Page.CELLULAR_SETTINGS, Endpoint.APN_DEFAULT_SAVE)
    async def set_default_apn(
        self,
        *,
        apn: str | None = None,
        profile_name: str | None = None,
        username: str | None = None,
        password: str | None = None,
        auth: ApnAuth | None = None,
        ip_type: ApnIpType | None = None,
    ) -> None:
        """Change the default APN profile; omitted fields are kept.

        As in the UI, text values go through ``decodeURIComponent`` before
        being sent (``%41`` becomes ``A``; a lone ``%`` is refused). The UI
        offers no way to disable the default profile (its switch is commented
        out), so neither does this method.
        """
        current = await self.get_settings()
        _require_sim(current)
        default = current.default_apn
        if default is None:
            invalid("the page holds no default APN profile")
        data = dict(default.raw)
        # on load the UI re-selects auth and IP type, normalising both
        if data.get("auth") not in {a.value for a in ApnAuth}:
            data["auth"] = ApnAuth.NONE.value
        data["IPType"] = _IP_TYPE_CODES[_ip_type(data.get("IPType"))]
        for key, value in (
            ("apn", apn),
            ("name", profile_name),
            ("user", username),
            ("passwd", password),
        ):
            if value is not None:
                data[key] = value
        if auth is not None:
            data["auth"] = ApnAuth(auth).value
        if ip_type is not None:
            data["IPType"] = _IP_TYPE_CODES[ApnIpType(ip_type)]

        raw_apn = str(data.get("apn", ""))
        if not raw_apn:
            invalid("the APN is empty")
        if js_length(raw_apn) > MAX_APN_LENGTH:
            invalid(f"the APN is longer than {MAX_APN_LENGTH} characters")
        if not is_valid_apn(raw_apn):
            invalid(f"invalid APN {raw_apn!r}")
        name = decode_uri_component(str(data.get("name", "")))
        if not name:
            invalid("the profile name is empty")
        if js_length(name) > MAX_PROFILE_NAME_LENGTH:
            invalid(f"the profile name is longer than {MAX_PROFILE_NAME_LENGTH} characters")
        data["name"] = name
        data["user"] = decode_uri_component(str(data.get("user", "")))
        data["passwd"] = decode_uri_component(str(data.get("passwd", "")))
        data["apn"] = decode_uri_component(raw_apn)

        def body(token: str | None) -> dict[str, Any]:
            return {**data, TOKEN_FIELD: token, "DefaultApnMode": "Manual"}

        await self._client._command(Endpoint.APN_DEFAULT_SAVE, body)

    @uses(Page.CELLULAR_SETTINGS, Endpoint.APN_ADD)
    async def add_apn(
        self,
        apn: str,
        *,
        profile_name: str = "",
        username: str = "",
        password: str = "",
        auth: ApnAuth = ApnAuth.NONE,
        ip_type: ApnIpType = ApnIpType.IPV4V6,
        enabled: bool = True,
    ) -> None:
        """Add an APN profile. Runs the UI's checks first (``apnAdd`` / ``apnAddSave``)."""
        auth, ip_type = ApnAuth(auth), ApnIpType(ip_type)
        current = await self.get_settings()
        _require_sim(current)
        if len(current.apns) >= MAX_APNS:
            invalid(f"the router holds at most {MAX_APNS} APN profiles")
        if any(apn == decode_uri_component(str(a.raw.get("apn", ""))) for a in current.apns):
            invalid(f"an APN profile for {apn!r} already exists")
        if auth is not ApnAuth.NONE and (not username or not password):
            invalid("authentication needs a username and a password")
        if not apn:
            invalid("the APN is empty")
        if js_length(apn) > MAX_APN_LENGTH:
            invalid(f"the APN is longer than {MAX_APN_LENGTH} characters")
        if not is_valid_apn(apn):
            invalid(f"invalid APN {apn!r}")

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "disable": 0 if enabled else 1,
                "name": profile_name,
                "apn": apn,
                "auth": auth.value,
                "user": username,
                "passwd": password,
                "IPType": _IP_TYPE_CODES[ip_type],
            }

        await self._client._command(Endpoint.APN_ADD, body)

    @uses(Page.CELLULAR_SETTINGS, Endpoint.APN_EDIT)
    async def edit_apn(
        self,
        instance: int,
        *,
        apn: str | None = None,
        profile_name: str | None = None,
        username: str | None = None,
        password: str | None = None,
        auth: ApnAuth | None = None,
        ip_type: ApnIpType | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Change a user APN profile (``instance`` is :attr:`Apn.instance`).

        Omitted fields keep their current value. Runs the UI's checks first
        (``apnEditSave``).
        """
        current = await self.get_settings()
        _require_sim(current)
        entry = _user_apn(current, instance)
        raw = entry.raw
        # the edit dialog is pre-filled with the decoded values
        new_name = (
            decode_uri_component(str(raw.get("name", ""))) if profile_name is None else profile_name
        )
        new_apn = decode_uri_component(str(raw.get("apn", ""))) if apn is None else apn
        new_user = decode_uri_component(str(raw.get("user", ""))) if username is None else username
        new_pass = (
            decode_uri_component(str(raw.get("passwd", ""))) if password is None else password
        )
        new_auth = ApnAuth(auth).value if auth is not None else str(raw.get("auth", "NONE"))
        if new_auth not in {a.value for a in ApnAuth}:
            new_auth = ApnAuth.NONE.value
        new_type = _IP_TYPE_CODES[
            ApnIpType(ip_type) if ip_type is not None else _strict_ip_type(raw.get("IPType"))
        ]
        new_disable = (
            (0 if enabled else 1) if enabled is not None else parse_int(raw.get("disable"))
        )

        for other in current.apns:
            if other.instance == entry.instance:
                continue
            if new_apn == decode_uri_component(str(other.raw.get("apn", ""))):
                invalid(f"an APN profile for {new_apn!r} already exists")
        if new_apn and new_name:
            if js_length(new_apn) > MAX_APN_LENGTH:
                invalid(f"the APN is longer than {MAX_APN_LENGTH} characters")
            if not is_valid_apn(new_apn):
                invalid(f"invalid APN {new_apn!r}")
            if js_length(new_name) > MAX_PROFILE_NAME_LENGTH:
                invalid(f"the profile name is longer than {MAX_PROFILE_NAME_LENGTH} characters")
            if new_auth != ApnAuth.NONE.value and (not new_user or not new_pass):
                invalid("authentication needs a username and a password")
        elif not new_name:
            invalid("the profile name is empty")
        else:
            invalid("the APN is empty")

        data = dict(raw)
        data.update(
            disable=0 if new_disable == 0 else 1,
            IPType=new_type,
            name=new_name,
            apn=new_apn,
            user=new_user,
            passwd=new_pass,
            auth=new_auth,
        )

        def body(token: str | None) -> dict[str, Any]:
            return {**data, TOKEN_FIELD: token}

        await self._client._command(Endpoint.APN_EDIT, body)

    @uses(Page.CELLULAR_SETTINGS, Endpoint.APN_DELETE)
    async def delete_apn(self, instance: int) -> None:
        """Delete a user APN profile (``instance`` is :attr:`Apn.instance`)."""
        current = await self.get_settings()
        _require_sim(current)
        entry = _user_apn(current, instance)
        data = dict(entry.raw)

        def body(token: str | None) -> dict[str, Any]:
            return {**data, TOKEN_FIELD: token}

        await self._client._command(Endpoint.APN_DELETE, body)

    @uses(Endpoint.PIN_ENTER)
    async def enter_pin(self) -> NoReturn:
        """Not supported by policy: wrong PINs burn SIM retries."""
        self._unsupported(Endpoint.PIN_ENTER)

    @uses(Endpoint.PUK_ENTER)
    async def enter_puk(self) -> NoReturn:
        """Not supported by policy: wrong PUKs lock the SIM permanently."""
        self._unsupported(Endpoint.PUK_ENTER)

    @uses(Endpoint.CHANGE_PIN)
    async def change_pin(self) -> NoReturn:
        """Not supported by policy (SIM PIN management)."""
        self._unsupported(Endpoint.CHANGE_PIN)

    @uses(Endpoint.PIN_LOCK)
    async def set_pin_lock(self) -> NoReturn:
        """Not supported by policy (SIM PIN management)."""
        self._unsupported(Endpoint.PIN_LOCK)
