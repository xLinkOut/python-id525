"""IP filter rules (``fw-ipfilter`` page)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, Page, uses
from ..models import _raw
from ..parsers import extract_js_values
from .base import Section, invalid

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_IP_FILTER_RULES = 10
"""The UI disables *Add* once the list holds 10 rules."""

# Ported verbatim from the page. IPv6_CIDR keeps the page's own bugs (``^s*``,
# ``d`` instead of ``\d`` in the embedded-IPv4 parts): the client must refuse
# exactly what the UI refuses. JS ``$`` == Python ``\Z``; JS ``\d`` is ASCII.
_IPV4_CIDR = re.compile(
    r"^(?=\d+\.\d+\.\d+\.\d+(\Z|\/))(([1-9]?\d|1\d\d|2[0-4]\d|25[0-5])\.?){4}?\Z", re.ASCII
)
_IPV6_CIDR = re.compile(
    r"^s*((([0-9A-Fa-f]{1,4}:){7}([0-9A-Fa-f]{1,4}|:))|(([0-9A-Fa-f]{1,4}:){6}(:[0-9A-Fa-f"
    r"]{1,4}|((25[0-5]|2[0-4]d|1dd|[1-9]?d)(.(25[0-5]|2[0-4]d|1dd|[1-9]?d)){3})|:))|(([0-9"
    r"A-Fa-f]{1,4}:){5}(((:[0-9A-Fa-f]{1,4}){1,2})|:((25[0-5]|2[0-4]d|1dd|[1-9]?d)(.(25[0-"
    r"5]|2[0-4]d|1dd|[1-9]?d)){3})|:))|(([0-9A-Fa-f]{1,4}:){4}(((:[0-9A-Fa-f]{1,4}){1,3})|"
    r"((:[0-9A-Fa-f]{1,4})?:((25[0-5]|2[0-4]d|1dd|[1-9]?d)(.(25[0-5]|2[0-4]d|1dd|[1-9]?d))"
    r"{3}))|:))|(([0-9A-Fa-f]{1,4}:){3}(((:[0-9A-Fa-f]{1,4}){1,4})|((:[0-9A-Fa-f]{1,4}){0,"
    r"2}:((25[0-5]|2[0-4]d|1dd|[1-9]?d)(.(25[0-5]|2[0-4]d|1dd|[1-9]?d)){3}))|:))|(([0-9A-F"
    r"a-f]{1,4}:){2}(((:[0-9A-Fa-f]{1,4}){1,5})|((:[0-9A-Fa-f]{1,4}){0,3}:((25[0-5]|2[0-4]"
    r"d|1dd|[1-9]?d)(.(25[0-5]|2[0-4]d|1dd|[1-9]?d)){3}))|:))|(([0-9A-Fa-f]{1,4}:){1}(((:["
    r"0-9A-Fa-f]{1,4}){1,6})|((:[0-9A-Fa-f]{1,4}){0,4}:((25[0-5]|2[0-4]d|1dd|[1-9]?d)(.(25"
    r"[0-5]|2[0-4]d|1dd|[1-9]?d)){3}))|:))|(:(((:[0-9A-Fa-f]{1,4}){1,7})|((:[0-9A-Fa-f]{1,"
    r"4}){0,5}:((25[0-5]|2[0-4]d|1dd|[1-9]?d)(.(25[0-5]|2[0-4]d|1dd|[1-9]?d)){3}))|:)))(%."
    r"+)?s*?\Z"
)
_ENTRIES_RE = re.compile(r"\bvar\s+ipFilter_entries\s*=\s*(['\"])(.*?)\1\s*;")


class IpType(StrEnum):
    """Address family of a rule (``ipf_iptype``)."""

    IPV4 = "IPv4"
    IPV6 = "IPv6"


class FilterMode(StrEnum):
    """What the rules mean."""

    BLACKLIST = "blacklist"
    """Block the listed addresses."""
    WHITELIST = "whitelist"
    """Allow only the listed addresses."""


@dataclass(frozen=True, slots=True, kw_only=True)
class IpFilterRule:
    """One IP filter rule (an entry of ``ipFilter_entries``)."""

    instance: Any
    """Router-side id, as the router gives it (sent back as is)."""
    ip: str
    ip_type: str
    protocol: str | None
    raw: Mapping[str, Any] = _raw()


@dataclass(frozen=True, slots=True, kw_only=True)
class IpFilterSettings:
    """IP filter state as shown by the ``fw-ipfilter`` page."""

    enabled: bool
    mode: FilterMode
    rules: tuple[IpFilterRule, ...]
    raw: Mapping[str, Any] = _raw()


def parse_ip_filter_page(html: str) -> IpFilterSettings:
    """Parse the data the router embeds in ``fw-ipfilter.html``."""
    values = extract_js_values(html)
    match = _ENTRIES_RE.search(html)
    entries = json.loads(match.group(2).replace("&quot;", '"')) if match else []
    rules = tuple(
        IpFilterRule(
            instance=e.get("instance"),
            ip=str(e.get("dst_ip", "")),
            ip_type=str(e.get("ip_type", "")),
            protocol=e.get("protocol"),
            raw=e,
        )
        for e in entries
    )
    return IpFilterSettings(
        enabled=values.get("IPFilter_Enable") != "0",
        mode=FilterMode.WHITELIST
        if values.get("pkts_blocklist_mode") == "1"
        else FilterMode.BLACKLIST,
        rules=rules,
        raw=values,
    )


def _check_ip(ip: str, ip_type: IpType, rules: tuple[IpFilterRule, ...]) -> None:
    """UI ``btnOKClicked`` / ``edit_rule_save`` checks, in order."""
    if not ip:
        invalid("the IP address is empty")
    if any(rule.ip == ip for rule in rules):
        invalid(f"{ip} is already in the list")
    if ip_type is IpType.IPV4:
        first = ip.split(".", maxsplit=1)[0]
        bad = (
            not _IPV4_CIDR.search(ip)
            or (first.isdigit() and (224 <= int(first) <= 255 or int(first) == 127))
            or ip in ("255.255.255.255", "0.0.0.0")  # noqa: S104
        )
    else:
        bad = not _IPV6_CIDR.search(ip) or ip in ("0::0", "::1", "FF00::/8", "ff00::/8")
    if bad:
        invalid(f"invalid {ip_type} address {ip!r}")


def _find(settings: IpFilterSettings, instance: object) -> IpFilterRule:
    rule = next((r for r in settings.rules if str(r.instance) == str(instance)), None)
    if rule is None:
        invalid(f"no IP filter rule with instance {instance!r}")
    return rule


class IpFilterApi(Section):
    """IP filter rules."""

    @uses(Page.IP_FILTER)
    async def get_settings(self) -> IpFilterSettings:
        """Return the IP filter state and rules."""
        return parse_ip_filter_page(await self._client._page(Page.IP_FILTER))

    @uses(Page.IP_FILTER, Endpoint.IPFILTER_ADD)
    async def add_rule(self, ip: str, ip_type: IpType = IpType.IPV4) -> None:
        """Add an address to the list. Runs the UI's checks first."""
        ip_type = IpType(ip_type)
        current = await self.get_settings()
        if len(current.rules) >= MAX_IP_FILTER_RULES:
            invalid(f"the router holds at most {MAX_IP_FILTER_RULES} IP filter rules")
        _check_ip(ip, ip_type, current.rules)
        is_edit = current.raw.get("is_edit", "0")
        edit_instance = current.raw.get("edit_instance", "")

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "is_edit": is_edit,
                "edit_instance": edit_instance,
                "ipf_lanipAddr": "",
                "ipf_lan_port": "",
                "ipf_wanipAddr": ip,
                "ipf_wan_port": "",
                "ipf_protocol": "",
                "ipf_iptype": ip_type.value,
            }

        await self._client._command(Endpoint.IPFILTER_ADD, body)

    @uses(Page.IP_FILTER, Endpoint.IPFILTER_EDIT)
    async def edit_rule(self, instance: str, ip: str, ip_type: IpType | None = None) -> None:
        """Change a rule's address (and family; default: keep it).

        Like the UI, the new address must differ from every listed one,
        including the rule's own.
        """
        current = await self.get_settings()
        rule = _find(current, instance)
        new_type = IpType(ip_type) if ip_type is not None else IpType(rule.ip_type)
        _check_ip(ip, new_type, current.rules)

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "edit_instance": rule.instance,
                "ipf_wanipAddr": ip,
                "ipf_iptype": new_type.value,
            }

        await self._client._command(Endpoint.IPFILTER_EDIT, body)

    @uses(Page.IP_FILTER, Endpoint.IPFILTER_SAVE)
    async def delete_rule(self, instance: str) -> None:
        """Delete a rule."""
        rule = _find(await self.get_settings(), instance)

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "apply": "del", "del_rule": rule.instance}

        await self._client._command(Endpoint.IPFILTER_SAVE, body)

    @uses(Page.IP_FILTER, Endpoint.IPFILTER_SAVE)
    async def set_filter(
        self, *, enabled: bool | None = None, mode: FilterMode | None = None
    ) -> None:
        """Switch the filter on / off and choose its mode (omitted: keep)."""
        current = await self.get_settings()
        if enabled is None:
            switch = str(current.raw.get("IPFilter_Enable", "0"))  # untouched: page value
        else:
            switch = "1" if enabled else "0"
        new_mode = current.mode if mode is None else FilterMode(mode)

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "apply": "apply",
                "ipfilter_enable": switch,
                "pkts_blocklist_mode": "1" if new_mode is FilterMode.WHITELIST else "0",
            }

        await self._client._command(Endpoint.IPFILTER_SAVE, body)
