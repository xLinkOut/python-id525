"""VoIP / SIP line settings (``voip-settings`` page).

The page fills its form from literals the router writes into the page's script
(``voip_SIP_Domain_text ... .value = "..."``) and a few ``var`` flags. Saving
(``voip_apply``) posts every field; the SIP password is sent only if it was
changed: the page holds an opaque blob in its place, and an untouched blob is
sent as ``sip_password: ""`` with ``donotset_pass: 1``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import IntEnum
from html import unescape
from typing import TYPE_CHECKING, Any

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, Page, uses
from ..exceptions import Id525CommandError
from ..models import _raw
from ..parsers import clean_str
from .base import Section, invalid
from .wifi import js_decode_uri_component

if TYPE_CHECKING:
    from collections.abc import Mapping

ETH_WAN = "ETH WAN"
"""``bind_interface`` value selecting the Ethernet WAN port (when the router has one)."""
_ETH_WAN_HANDLE = 6
_FIELD_RE = r'-voip_{name}_text"\)\.value\s*=\s*(decodeURIComponent\()?"((?:[^"\\]|\\.)*)"'
_NUMERIC_VAR_RE = re.compile(r"\bvar\s+(\w+)\s*=\s*(-?\d+)\s*;")
_APN_VAR_RE = re.compile(r"\bvar\s+(defaultApnInfo|user[1-4]ApnInfo)\s*=\s*'(.*?)'\s*;")
_FQDN_RE = re.compile(  # validateFQDN (js/validate.js)
    r"(?=^.{1,254}$)(^(?:(?!\d+\.|-)[a-zA-Z0-9_\-]{1,63}(?<!-)\.?)+(?:[a-zA-Z]{2,})$)", re.ASCII
)
_ADDRESS_FIELDS = (
    ("sip_domain", "SIP domain"),
    ("proxy_server", "proxy server"),
    ("outbound_proxy", "outbound proxy"),
)


class RegistrationStatus(IntEnum):
    """SIP registration state (``regist_status``)."""

    UP = 0
    INITIALIZING = 1
    REGISTERING = 2
    UNREGISTERING = 3
    ERROR = 4
    TESTING = 5
    QUIESCENT = 6
    DISABLED = 7


@dataclass(frozen=True, slots=True, kw_only=True)
class VoipApn:
    """A cellular profile the VoIP line can be bound to."""

    profile_handle: int
    apn: str
    enabled: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class VoipSettings:
    """VoIP line configuration and state."""

    registration_status: RegistrationStatus | None
    """``None`` for a value the UI does not know (it shows "Disabled")."""
    sip_domain: str | None
    proxy_server: str | None
    outbound_proxy: str | None
    account: str | None
    phone_number: str | None
    password_blob: str
    """Opaque stand-in for the SIP password (the router never shows the password)."""
    dns_srv: bool
    line_enabled: bool
    pos_mode: bool
    bind_interface: int
    """Profile handle of the bound APN (6 = Ethernet WAN)."""
    apns: tuple[VoipApn, ...]
    eth_wan: bool
    """The router offers binding to the Ethernet WAN port."""
    raw: Mapping[str, Any] = _raw()

    @property
    def bound_apn(self) -> str | None:
        """Return the APN the line is bound to (``"ETH WAN"`` for the Ethernet port)."""
        if self.bind_interface == _ETH_WAN_HANDLE and self.eth_wan:
            return ETH_WAN
        return next((a.apn for a in self.apns if a.profile_handle == self.bind_interface), None)


def _field(html: str, name: str) -> str:
    """Return the value the page puts in a form field (decoded where the UI decodes)."""
    match = re.search(_FIELD_RE.replace("{name}", re.escape(name)), html)
    if match is None:
        return ""
    value = str(json.loads(f'"{match.group(2)}"'))  # a JS double-quoted string literal
    if match.group(1):
        try:
            return js_decode_uri_component(value)
        except ValueError:
            return value
    return value


def _form(html: str) -> dict[str, str]:
    """Return the text fields exactly as the UI shows (and would send) them."""
    return {
        "sip_domain": _field(html, "SIP_Domain"),
        "proxy_server": _field(html, "proxy_server"),
        "outbound_proxy": _field(html, "outbound_proxy"),
        "sip_account": _field(html, "account"),
        "sip_password": _field(html, "password"),
        "sip_callID": _field(html, "telephone_num"),
    }


def parse_voip_page(html: str) -> VoipSettings:
    """Parse the data the router embeds in ``voip-settings.html``."""
    numbers = {m.group(1): int(m.group(2)) for m in _NUMERIC_VAR_RE.finditer(html)}
    apns = []
    for match in _APN_VAR_RE.finditer(html):
        text = match.group(2)
        if len(text) <= 2:  # '{}': no such profile
            continue
        data = json.loads(unescape(text))
        apns.append(
            VoipApn(
                profile_handle=int(data.get("profile_handle", 0)),
                apn=str(data.get("apn", "")),
                enabled=str(data.get("disable")) == "0",
            )
        )
    status = numbers.get("regist_status")
    form = _form(html)
    return VoipSettings(
        registration_status=(
            RegistrationStatus(status) if status in {s.value for s in RegistrationStatus} else None
        ),
        sip_domain=clean_str(form["sip_domain"]),
        proxy_server=clean_str(form["proxy_server"]),
        outbound_proxy=clean_str(form["outbound_proxy"]),
        account=clean_str(form["sip_account"]),
        phone_number=clean_str(form["sip_callID"]),
        password_blob=form["sip_password"],
        dns_srv=numbers.get("dnssrv") == 1,
        line_enabled=numbers.get("lineEnable") == 1,
        pos_mode=numbers.get("posModeEnable") == 1,
        bind_interface=numbers.get("bindInterface", 0),
        apns=tuple(apns),
        eth_wan=numbers.get("is_ethWan") == 1,
        raw={**numbers, **{k: v for k, v in form.items() if k != "sip_password"}},
    )


def _check_ip(value: str) -> bool:
    """UI ``checkIP`` (js/validate.js): four all-digit octets in 0-255."""
    parts = value.split(".")
    return len(parts) == 4 and all(
        part != "" and all("0" <= c <= "9" for c in part) and 0 <= int(part) <= 255
        for part in parts
    )


def _address_ok(value: str) -> bool:
    return bool(_FQDN_RE.match(value)) or _check_ip(value)


class VoipApi(Section):
    """VoIP / SIP line."""

    @uses(Page.VOIP_SETTINGS)
    async def get_settings(self) -> VoipSettings:
        """Return the SIP settings, the registration state and the bindable APNs."""
        return parse_voip_page(await self._client._page(Page.VOIP_SETTINGS))

    @uses(Page.VOIP_SETTINGS, Endpoint.VOIP_APPLY)
    async def update(
        self,
        *,
        sip_domain: str | None = None,
        proxy_server: str | None = None,
        outbound_proxy: str | None = None,
        account: str | None = None,
        password: str | None = None,
        phone_number: str | None = None,
        dns_srv: bool | None = None,
        line_enabled: bool | None = None,
        pos_mode: bool | None = None,
        bind_interface: str | None = None,
    ) -> None:
        """Change the VoIP line; omitted fields keep their current value.

        ``password`` is sent only when given. ``bind_interface`` is an APN name
        from :attr:`VoipSettings.apns` (or ``"ETH WAN"``). Runs the UI's
        checks first: a proxy or outbound proxy and a phone number are
        required, and the three server fields must be host names or IPv4
        addresses.
        """
        html = await self._client._page(Page.VOIP_SETTINGS)
        current = parse_voip_page(html)
        form = _form(html)
        changes = {
            "sip_domain": sip_domain,
            "proxy_server": proxy_server,
            "outbound_proxy": outbound_proxy,
            "sip_account": account,
            "sip_password": password,
            "sip_callID": phone_number,
        }
        for key, value in changes.items():
            if value is not None:
                form[key] = value
        dns = int(current.dns_srv if dns_srv is None else dns_srv)
        line = int(current.line_enabled if line_enabled is None else line_enabled)
        pos = int(current.pos_mode if pos_mode is None else pos_mode)
        bind = (
            current.bind_interface if bind_interface is None else _handle(current, bind_interface)
        )

        # apply_voip's checks, in its order
        if not form["outbound_proxy"] and not form["proxy_server"]:
            invalid("set a proxy server or an outbound proxy")
        if not form["sip_callID"]:
            invalid("the telephone number is empty")
        for key, label in _ADDRESS_FIELDS:
            if form[key] and not _address_ok(form[key]):
                invalid(f"the {label} {form[key]!r} is not a host name or IPv4 address")
        unchanged_password = form["sip_password"] == current.password_blob

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "sip_domain": form["sip_domain"],
                "proxy_server": form["proxy_server"],
                "outbound_proxy": form["outbound_proxy"],
                "sip_account": form["sip_account"],
                "sip_password": "" if unchanged_password else form["sip_password"],
                "donotset_pass": 1 if unchanged_password else 0,
                "sip_callID": form["sip_callID"],
                "DNS_SRV": dns,
                "LINE_Enable": line,
                "pos_mode_enable": pos,
                "bindInterface": bind,
            }

        data = await self._client._call(Endpoint.VOIP_APPLY, body)
        if data.get("result") is False:
            raise Id525CommandError(Endpoint.VOIP_APPLY, data.get("error_code", data.get("error")))


def _handle(current: VoipSettings, interface: str) -> int:
    if interface == ETH_WAN:
        if not current.eth_wan:
            invalid("this router has no Ethernet WAN port to bind to")
        return _ETH_WAN_HANDLE
    handle = next(
        (a.profile_handle for a in current.apns if a.enabled and a.apn == interface), None
    )
    if handle is None:
        offered = [a.apn for a in current.apns if a.enabled]
        invalid(f"{interface!r} is not an enabled APN; choose one of {offered}")
    return handle
