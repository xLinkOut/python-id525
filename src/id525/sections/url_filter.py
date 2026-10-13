"""URL filter / parental control (``fw-urlfilter`` page)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, Page, uses
from ..models import _raw
from ..parsers import extract_js_values, parse_int
from .base import Section, invalid
from .ip_filter import FilterMode

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_URL_FILTER_RULES = 10
"""The UI disables *Add* once the list holds 10 URLs."""
MAX_URL_LENGTH = 127

# js/validate.js validateURL / isValidURLStr, ported verbatim (ASCII \b, JS $ == \Z).
_HTTP_RE = re.compile(
    r"^https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b"
    r"(?:[-a-zA-Z0-9()@:%_\+.~#?&\/=]*)\Z",
    re.ASCII,
)
_NO_HTTP_RE = re.compile(
    r"^[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)\Z",
    re.ASCII,
)
_URL_FORBIDDEN = "`,\";&%+'<>?¥" + "￥"  # url_not_allow_letter + special_symbol
_PROFILE_RE = re.compile(r"\bvar\s+parent_control_profile_get\s*=\s*\"(.*?)\"\s*;", re.DOTALL)


@dataclass(frozen=True, slots=True, kw_only=True)
class UrlFilterRule:
    """One filtered URL."""

    instance: str
    """Router-side id (sent back in edit / delete requests)."""
    url: str


@dataclass(frozen=True, slots=True, kw_only=True)
class UrlFilterSettings:
    """URL filter state as shown by the ``fw-urlfilter`` page."""

    enabled: bool
    mode: FilterMode
    rules: tuple[UrlFilterRule, ...]
    raw: Mapping[str, Any] = _raw()


def parse_rules(profile: str) -> tuple[UrlFilterRule, ...]:
    """Parse ``"<instance>,<url>;<instance>,<url>;"`` like the UI does.

    The UI drops the last ``;``-separated item (normally empty after the
    trailing ``;``), so a value without any ``;`` holds no rule. Unreadable
    values (seen in the wild: a few garbage bytes) therefore yield nothing.
    """
    rules = []
    for item in profile.split(";")[:-1]:
        parts = item.split(",")
        rules.append(UrlFilterRule(instance=parts[0], url=parts[1] if len(parts) > 1 else ""))
    return tuple(rules)


def parse_url_filter_page(html: str) -> UrlFilterSettings:
    """Parse the data the router embeds in ``fw-urlfilter.html``."""
    values = extract_js_values(html)
    match = _PROFILE_RE.search(html)
    profile = match.group(1) if match else ""
    return UrlFilterSettings(
        enabled=parse_int(values.get("parent_control_profile_enabled")) not in (0, None),
        mode=FilterMode.WHITELIST if values.get("isAllow") == "1" else FilterMode.BLACKLIST,
        rules=parse_rules(profile),
        raw={**values, "parent_control_profile_get": profile},
    )


def _check_url(url: str, rules: tuple[UrlFilterRule, ...]) -> None:
    """UI ``add_urlfilter`` / ``edit_rule_save`` checks, in order."""
    if not url:
        invalid("the URL is empty")
    if len(url) > MAX_URL_LENGTH:
        invalid(f"the URL is longer than {MAX_URL_LENGTH} characters")
    pattern = _HTTP_RE if url.startswith("http") else _NO_HTTP_RE
    if not pattern.search(url):
        invalid(f"invalid URL {url!r}")
    if any(c in _URL_FORBIDDEN for c in url):
        invalid(f"the URL {url!r} contains a forbidden symbol")
    if any(rule.url == url for rule in rules):
        invalid(f"{url} is already in the list")


def _find(settings: UrlFilterSettings, instance: str) -> UrlFilterRule:
    rule = next((r for r in settings.rules if r.instance == str(instance)), None)
    if rule is None:
        invalid(f"no URL filter rule with instance {instance!r}")
    return rule


class UrlFilterApi(Section):
    """URL filter (parental control)."""

    @uses(Page.URL_FILTER)
    async def get_settings(self) -> UrlFilterSettings:
        """Return the URL filter state and rules."""
        return parse_url_filter_page(await self._client._page(Page.URL_FILTER))

    @uses(Page.URL_FILTER, Endpoint.URLFILTER_STATUS)
    async def set_filter(
        self, *, enabled: bool | None = None, mode: FilterMode | None = None
    ) -> None:
        """Switch the filter on / off and choose its mode (omitted: keep)."""
        current = await self.get_settings()
        state = current.enabled if enabled is None else enabled
        new_mode = current.mode if mode is None else FilterMode(mode)

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "state": 1 if state else 0,
                "mode": 1 if new_mode is FilterMode.WHITELIST else 0,
            }

        await self._client._command(Endpoint.URLFILTER_STATUS, body)

    @uses(Page.URL_FILTER, Endpoint.URLFILTER_ADD)
    async def add_url(self, url: str) -> None:
        """Add a URL to the list. Runs the UI's checks first."""
        current = await self.get_settings()
        if len(current.rules) >= MAX_URL_FILTER_RULES:
            invalid(f"the router holds at most {MAX_URL_FILTER_RULES} URL filter rules")
        _check_url(url, current.rules)

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "url_addr": url}

        await self._client._command(Endpoint.URLFILTER_ADD, body)

    @uses(Page.URL_FILTER, Endpoint.URLFILTER_EDIT)
    async def edit_url(self, instance: str, url: str) -> None:
        """Replace a rule's URL. Like the UI, it must differ from every listed URL."""
        current = await self.get_settings()
        rule = _find(current, instance)
        _check_url(url, current.rules)

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "edit_instance": rule.instance, "new_url_addr": url}

        await self._client._command(Endpoint.URLFILTER_EDIT, body)

    @uses(Page.URL_FILTER, Endpoint.URLFILTER_DELETE)
    async def delete_url(self, instance: str) -> None:
        """Delete a rule."""
        rule = _find(await self.get_settings(), instance)

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "del_instance": rule.instance}

        await self._client._command(Endpoint.URLFILTER_DELETE, body)
