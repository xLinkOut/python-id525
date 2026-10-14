"""Record what the client did, to debug it from a file instead of from the router.

A :class:`TraceRecorder` passed to :class:`~id525.client.Id525Client` (``tracer=``)
gets one event per HTTP exchange: the exact request bytes, the raw answer (also
non-JSON and HTTP-error answers), the timing, and the transport error if any.
Callers add their own events (the CLI records the command, the result and the
traceback). :meth:`TraceRecorder.write` saves the events as JSON lines.

Traces are **redacted by default**, since they end up pasted into issues and
chats. Credentials, CSRF tokens and session cookies are replaced by stable
pseudonyms (``TOKEN-3`` is the same token everywhere, so token rotation stays
debuggable), and so are identity values: IMEI/IMSI/ICCID, serials, phone
numbers, SMS texts, cell ids (a location), MACs, SSIDs, device and host names,
WAN addresses. Values
are found by key (in JSON bodies, in JSON nested in strings, in the HTML-entity
JSON and ``var x = '...'`` of pages), replaced in every encoded form across the
whole trace, then a pattern sweep catches MACs, long digit ids and public IPs.
Redaction is best effort: read a trace before publishing it.
"""

from __future__ import annotations

import contextlib
import html
import ipaddress
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import quote, unquote

if TYPE_CHECKING:
    from pathlib import Path


class Tracer(Protocol):
    """Receives trace events from the client."""

    def record(self, event: str, /, **data: Any) -> None:
        """Record one event."""


# Key name -> category. First match wins; checked against the whole key name.
_KEY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("TOKEN", re.compile(r"RequestVerifyToken|.*token", re.I)),
    (
        "SECRET",
        re.compile(
            r".*(pass(word|wd|phrase)?|pwd|psk|secret)(_?o|_?back)?|pin_code|puk(_?code)?|"
            r"new_?pin|old_?pin|input_\w*pwd|donotset_pass",
            re.I,
        ),
    ),
    ("IMEI", re.compile(r"imei\w*", re.I)),
    ("IMSI", re.compile(r"imsi\w*", re.I)),
    ("ICCID", re.compile(r"iccid\w*", re.I)),
    ("SERIAL", re.compile(r"serial\w*|sn|sw_?sn|board_?sn", re.I)),
    (
        "PHONE",
        re.compile(
            r"msisdn\w*|phone_?num(ber)?s?|recipients|sip_(account|callid)|"
            r"voip_(account|user(name)?|number|phone)\w*",
            re.I,
        ),
    ),
    ("CELL", re.compile(r"cell_?id|eci|nci|[eg]nb(_?id)?|tac|lac|ci", re.I)),
    ("TEXT", re.compile(r"context|smscontext|sms_?(text|body|content)|text", re.I)),
    (
        "MAC",
        re.compile(
            r"(eth_|old_|edit|client|router|current_device_)?mac(_?addr)?|routermac|"
            r"lastsixmac",
            re.I,
        ),
    ),
    ("SSID", re.compile(r"_?(cur)?ssid(_[25]g)?|wifi_?name", re.I)),
    (
        "NAME",
        re.compile(
            r"hostname|host_name|devicename|device_name|old_devname|w_name|"
            r"ddns_(host_name|user_name)|ddns_(hostname|login)|_?fqdn|domainname|"
            r"sip_domain|username|usr|user|input_username|account|"
            r"(voip|sip)_\w*(proxy|server|registrar|domain)\w*|outbound_proxy|proxy_server|"
            r"name",
            re.I,
        ),
    ),
    ("IP", re.compile(r"_?ipv[46]_(addr|gw|prefix)|wan_?ip\w*|public_?ip", re.I)),
)

# "key":"value" / "key":123, with plain, backslash-escaped or entity quotes.
_PAIR_RES = (
    re.compile(
        r'(?<!\\)"(?P<key>[A-Za-z_]\w*)"\s*:\s*(?:"(?P<val>(?:\\.|[^"\\])*)"|(?P<num>-?\d+))'
    ),
    re.compile(r'\\"(?P<key>[A-Za-z_]\w*)\\"\s*:\s*(?:\\"(?P<val>.*?)\\"|(?P<num>-?\d+))'),
    re.compile(
        r"(?P<q>&quot;|&#34;)(?P<key>[A-Za-z_]\w*)(?P=q)\s*:\s*"
        r"(?:(?P=q)(?P<val>.*?)(?P=q)|(?P<num>-?\d+))"
    ),
)
_VAR_RE = re.compile(r"\bvar\s+(?P<key>\w+)\s*=\s*(?P<vq>['\"])(?P<val>[^'\"\n]*)(?P=vq)")
# The UI also fills inputs from inline JS: getElementById(x + "-voip_account_text").value = "..."
_DOM_RE = re.compile(
    r"getElementById\([^)]*?[\"'](?:[\w]*-)?(?P<key>[\w]+?)(?:_text|_input|_value)?[\"']\)"
    r"\.(?:value|innerHTML|textContent|innerText)\s*=\s*(?:decodeURIComponent\()?"
    r"(?P<vq>[\"'])(?P<val>[^\"'\n]*)(?P=vq)"
)
_COOKIE_RE = re.compile(r"QSESSIONID=(?P<val>[^;\s\"',]+)")

_MAC_RE = re.compile(
    r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}(?:([:-])[0-9A-Fa-f]{2})(?:\1[0-9A-Fa-f]{2}){4}(?![0-9A-Fa-f:-])"
)
_LONG_DIGITS_RE = re.compile(r"(?<![\w.])\+?\d{11,20}(?![\w.])")
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_IPV6_RE = re.compile(r"(?<![\w:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![\w:])")

_PCT_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_KEEP_MACS = {"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"}
_KEEP_IPS = {"8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9"}
_KEEP_VALUES = {"", "admin", "n/a", "na", "none", "null", "--", "---"}

_PSEUDO_RE = re.compile(r"[A-Z]+-\d+")  # an already-made pseudonym


def _category(key: str) -> str | None:
    for category, rule in _KEY_RULES:
        if rule.fullmatch(key):
            return category
    return None


def _is_global_ip(value: str) -> bool:
    """Return True unless the value is a non-routable IP (private, CGNAT, link-local...)."""
    try:
        return ipaddress.ip_address(value.split("/", maxsplit=1)[0]).is_global
    except ValueError:
        return True  # not an address: redact to be safe


def _decode(value: str) -> str:
    """Undo the entity / JSON / URI escaping a value may carry inside a page or body."""
    value = html.unescape(value)
    if "\\" in value:
        with contextlib.suppress(ValueError):
            value = json.loads(f'"{value}"')
    if _PCT_RE.search(value):
        value = unquote(value)
    return value


def _encoded_forms(value: str) -> list[str]:
    """Every way a value can appear in a body or page, longest first."""
    pct = "".join(c if c.isalnum() else f"%{ord(c):02x}" for c in value)
    forms = {
        value,
        quote(value),
        quote(value, safe=""),
        pct,
        "".join(c if c.isalnum() else f"%{ord(c):02X}" for c in value),
        html.escape(value),
        html.escape(value).replace("&quot;", "&#34;"),
        json.dumps(value, ensure_ascii=False)[1:-1],
        json.dumps(value)[1:-1],
        json.dumps(value, ensure_ascii=False)[1:-1].replace("/", "\\/"),
    }
    return sorted((f for f in forms if f), key=len, reverse=True)


@dataclass
class Redactor:
    """Replace sensitive values by stable pseudonyms (``MAC-1``, ``TOKEN-3``...)."""

    pseudonyms: dict[str, str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    def pseudonym(self, category: str, value: str) -> str:
        """Return the pseudonym of a value, creating it on first use."""
        if category == "MAC":
            value = value.lower().replace("-", ":")
        known = self.pseudonyms.get(value)
        if known is not None:
            return known
        n = self._counters.get(category, 0) + 1
        self._counters[category] = n
        if category == "MAC":
            alias = f"02:00:5e:10:{n // 256:02x}:{n % 256:02x}"  # RFC 7042 documentation range
        elif category == "IP" and ":" in value:
            alias = f"2001:db8::{n:x}"
        elif category == "IP":
            alias = f"203.0.113.{n % 256}"
        elif category in {"IMEI", "IMSI", "ICCID", "PHONE", "CELL"} and value.lstrip("+").isdigit():
            digits = len(value.lstrip("+"))
            alias = ("+" if value.startswith("+") else "") + f"{n}".rjust(digits, "0")
        else:
            alias = f"{category}-{n}"
        self.pseudonyms[value] = alias
        return alias

    def learn(self, text: str) -> None:
        """Collect sensitive values from a body, page or message (keyed spots only)."""
        matches = [m for rx in (*_PAIR_RES, _VAR_RE, _DOM_RE) for m in rx.finditer(text)]
        for match in matches:
            value = match.group("val")
            if value is None:
                value = match.groupdict().get("num") or ""
            self._learn_value(match.group("key"), value)
            if value[:1] in "{[" or "&quot;" in value:
                self.learn(_decode(value))  # JSON nested in a string
        for match in _COOKIE_RE.finditer(text):
            self.pseudonym("SESSION", match.group("val"))

    def _learn_value(self, key: str, raw: str | None) -> None:
        category = _category(key)
        if category is None or raw is None:
            return
        value = _decode(raw)
        if value.strip().lower() in _KEEP_VALUES or _PSEUDO_RE.fullmatch(value):
            return
        if value[:1] in "{[":  # a container, its leaves are learned separately
            return
        if category == "IP" and not _is_global_ip(value):  # e.g. a CGNAT WAN address
            return
        parts = [value]
        if category == "PHONE":
            parts += [p.strip() for p in re.split(r"[;,]", value) if p.strip()]
        for part in parts:
            if part.lower() not in _KEEP_VALUES:
                self.pseudonym(category, part)
                if raw != value:
                    self.pseudonyms.setdefault(raw, self.pseudonyms[part])

    def redact(self, text: str) -> str:
        """Replace every learned value (in all encodings), then sweep known patterns."""
        for value in sorted(self.pseudonyms, key=len, reverse=True):
            alias = self.pseudonyms[value]
            short = len(value) < 4
            for form in _encoded_forms(value):
                if short:  # only where it is a whole quoted/keyed value, never a substring
                    text = re.sub(
                        rf"(?:^|(?<=[\"'=:;,])){re.escape(form)}(?=[\"'&;,\\]|$)", alias, text
                    )
                else:
                    text = text.replace(form, alias)
        text = _MAC_RE.sub(self._mac, text)
        text = _LONG_DIGITS_RE.sub(lambda m: self.pseudonym("IMEI", m.group(0)), text)
        text = _IPV4_RE.sub(self._ipv4, text)
        return _IPV6_RE.sub(self._ipv6, text)

    def _mac(self, match: re.Match[str]) -> str:
        mac = match.group(0)
        norm = mac.lower().replace("-", ":")
        if norm in _KEEP_MACS or norm.startswith("02:00:5e:"):
            return mac
        return self.pseudonym("MAC", norm)

    def _ipv4(self, match: re.Match[str]) -> str:
        value = match.group(0)
        try:
            ip = ipaddress.IPv4Address(value)
        except ValueError:
            return value
        if not ip.is_global or value in _KEEP_IPS or ip in ipaddress.IPv4Network("203.0.113.0/24"):
            return value
        return self.pseudonym("IP", value)

    def _ipv6(self, match: re.Match[str]) -> str:
        value = match.group(0)
        try:
            ip = ipaddress.IPv6Address(value)
        except ValueError:
            return value
        if not ip.is_global or ip in ipaddress.IPv6Network("2001:db8::/32"):
            return value
        return self.pseudonym("IP", value)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(value, list | tuple):
        return [s for v in value for s in _strings(v)]
    return []


def _map_strings(value: Any, fn: Any) -> Any:
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {k: _map_strings(v, fn) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_map_strings(v, fn) for v in value]
    return value


@dataclass
class TraceRecorder:
    """Collect trace events in memory; :meth:`write` them as (redacted) JSON lines."""

    redact: bool = True
    events: list[dict[str, Any]] = field(default_factory=list)
    _start: float = field(default_factory=time.monotonic)

    def record(self, event: str, /, **data: Any) -> None:
        """Record one event, timestamped from the recorder's creation."""
        self.events.append(
            {
                "seq": len(self.events) + 1,
                "t": round(time.monotonic() - self._start, 3),
                "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "event": event,
                **data,
            }
        )

    def redacted_events(self) -> list[dict[str, Any]]:
        """Return the events, redacted unless ``redact=False``.

        Two passes over the whole trace: values seen anywhere (e.g. a MAC in a
        JSON answer) are also replaced where they appear without a key (a page).
        """
        if not self.redact:
            return [dict(e) for e in self.events]
        redactor = Redactor()
        for event in self.events:  # keyed values of the events themselves (e.g. kwargs)...
            redactor.learn(json.dumps(event, ensure_ascii=False, default=str))
        for text in _strings(self.events):  # ...and of the bodies and pages they carry
            redactor.learn(text)
        out = [_map_strings(e, redactor.redact) for e in self.events]
        out.append({"event": "redaction", "pseudonyms": sorted(set(redactor.pseudonyms.values()))})
        return out

    def write(self, path: Path) -> Path:
        """Write the trace as JSON lines (one event per line) and return the path."""
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = (json.dumps(e, ensure_ascii=False, default=str) for e in self.redacted_events())
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
