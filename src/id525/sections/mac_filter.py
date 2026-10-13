"""MAC filter (``fw-macfilter`` page).

The page also lists the connected clients and has a "rename client" dialog
(``set_host_name.cgi``), but that dialog reads an undefined variable
(``client_list``) and is never wired to a button, so the UI cannot send it:
the endpoint is registered as dead code and not implemented.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, Page, uses
from ..models import _raw
from ..parsers import extract_js_values, parse_clients
from .base import Section, invalid, is_mac

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..models import ConnectedClient

MAX_MAC_FILTER_RULES = 10
MAX_RULE_NAME_LENGTH = 32
CONNECTED_CLIENT_DESCRIPTION = "AddFromConnectedClients"
"""Description the UI gives rules added from the connected-client list."""
_RULE_NAME_RE = re.compile(r"^[A-Za-z0-9-.]+$")  # UI isValidInput


class MacFilterMode(StrEnum):
    """Whether listed MACs are the only ones allowed, or the ones blocked."""

    BLACKLIST = "blacklist"
    WHITELIST = "whitelist"

    @property
    def wire(self) -> str:
        """Return the value the router uses (``mode``)."""
        return "1" if self is MacFilterMode.WHITELIST else "0"


@dataclass(frozen=True, slots=True, kw_only=True)
class MacFilterRule:
    """One MAC filter entry."""

    instance: Any
    """Router-side id, sent back verbatim in edit / delete requests."""
    name: str
    mac: str
    raw: Mapping[str, Any] = _raw()


@dataclass(frozen=True, slots=True, kw_only=True)
class MacFilterSettings:
    """MAC filter state as shown by the ``fw-macfilter`` page."""

    enabled: bool
    mode: MacFilterMode
    rules: tuple[MacFilterRule, ...]
    clients: tuple[ConnectedClient, ...]
    """The connected clients the page offers to add."""
    raw: Mapping[str, Any] = _raw()


def _entity_json(values: Mapping[str, str], name: str) -> Any:
    return json.loads(values.get(name, "null").replace("&quot;", '"'))


def parse_mac_filter_page(html: str) -> MacFilterSettings:
    """Parse the data the router embeds in ``fw-macfilter.html``."""
    values = extract_js_values(html)
    rules = tuple(
        MacFilterRule(
            instance=entry.get("instance"),
            name=str(entry.get("description", "")),
            mac=str(entry.get("macAddress", "")),
            raw=entry,
        )
        for entry in _entity_json(values, "tmp") or []
    )
    return MacFilterSettings(
        enabled=values.get("mac_filter_state") == "1",
        mode=MacFilterMode.WHITELIST
        if values.get("mac_filter_mode") == "1"
        else MacFilterMode.BLACKLIST,
        rules=rules,
        clients=parse_clients(_entity_json(values, "clients_info") or {}),
        raw=values,
    )


def _has_mac(rules: tuple[MacFilterRule, ...], mac: str) -> bool:
    """UI ``isMACExist``: case-insensitive match against *every* rule."""
    return any(rule.mac.upper() == mac.upper() for rule in rules)


def _check_rule(rules: tuple[MacFilterRule, ...], name: str, mac: str) -> None:
    """Run the checks shared by the UI's ``add_rule`` and ``edit_rule_save``, in order."""
    if not name:
        invalid("the device name is empty")
    if not mac:
        invalid("the MAC address is empty")
    if _has_mac(rules, mac):
        invalid(f"{mac} already has a rule")
    if not is_mac(mac):
        invalid(f"invalid MAC address {mac!r}")
    if not _RULE_NAME_RE.match(name):
        invalid(f"the device name {name!r} may only use letters, digits, '-' and '.'")
    if len(name) > MAX_RULE_NAME_LENGTH:
        invalid(f"the device name is longer than {MAX_RULE_NAME_LENGTH} characters")


class MacFilterApi(Section):
    """MAC filter: on/off, whitelist/blacklist, rules."""

    @uses(Page.MAC_FILTER)
    async def get_settings(self) -> MacFilterSettings:
        """Return the filter state, its rules and the connected clients."""
        return parse_mac_filter_page(await self._client._page(Page.MAC_FILTER))

    async def _save(self, *, enabled: bool, mode: MacFilterMode | str | None) -> None:
        current = await self.get_settings()
        new_mode = current.mode if mode is None else MacFilterMode(mode)
        if enabled and new_mode is MacFilterMode.WHITELIST and not current.rules:
            invalid("a whitelist needs at least one rule")

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "mf_value": "1" if enabled else "0", "mode": new_mode.wire}

        await self._client._command(Endpoint.MACFILTER_SAVE, body)

    @uses(Page.MAC_FILTER, Endpoint.MACFILTER_SAVE)
    async def enable(self, mode: MacFilterMode | str | None = None) -> None:
        """Turn the filter on (``mode`` defaults to the current one).

        A whitelist with no rules is refused, as by the UI: it would lock every
        device out.
        """
        await self._save(enabled=True, mode=mode)

    @uses(Page.MAC_FILTER, Endpoint.MACFILTER_SAVE)
    async def disable(self) -> None:
        """Turn the filter off (the mode is kept)."""
        await self._save(enabled=False, mode=None)

    @uses(Page.MAC_FILTER, Endpoint.MACFILTER_ADD)
    async def add_rule(self, mac: str, name: str) -> None:
        """Add a MAC with a device name (UI "Add New"; ``add_rule`` checks first)."""
        current = await self.get_settings()
        if len(current.rules) >= MAX_MAC_FILTER_RULES:
            invalid(f"the router holds at most {MAX_MAC_FILTER_RULES} MAC filter rules")
        _check_rule(current.rules, name, mac)

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "description": name, "clientMac": mac}

        await self._client._command(Endpoint.MACFILTER_ADD, body)

    @uses(Page.MAC_FILTER, Endpoint.MACFILTER_ADD)
    async def add_connected_client(self, mac: str) -> None:
        """Add a connected client's MAC (UI "From Available" or the client-list button).

        The rule gets the UI's fixed description ``AddFromConnectedClients``.
        The client-list button stays usable at the 10-rule limit, so no limit
        is checked here.
        """
        current = await self.get_settings()
        client = next((c for c in current.clients if c.mac == mac.lower()), None)
        if client is None:
            invalid(f"{mac} is not a connected client")
        listed = str(client.raw.get("mac", client.mac))
        if _has_mac(current.rules, listed):
            invalid(f"{mac} already has a rule")

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "description": CONNECTED_CLIENT_DESCRIPTION,
                "clientMac": listed,
            }

        await self._client._command(Endpoint.MACFILTER_ADD, body)

    @uses(Page.MAC_FILTER, Endpoint.MACFILTER_EDIT)
    async def modify_rule(
        self, instance: int, *, name: str | None = None, mac: str | None = None
    ) -> None:
        """Change a rule (``instance`` is :attr:`MacFilterRule.instance`).

        Quirk kept from the UI: the new MAC is checked against *all* rules,
        including the one being edited, so the MAC must change.
        """
        current = await self.get_settings()
        rule = next((r for r in current.rules if r.instance == instance), None)
        if rule is None:
            invalid(f"no MAC filter rule with instance {instance}")
        new_name = rule.name if name is None else name
        new_mac = rule.mac if mac is None else mac
        _check_rule(current.rules, new_name, new_mac)

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "edit_instance": rule.instance,
                "desc": new_name,
                "clientMac": new_mac,
            }

        await self._client._command(Endpoint.MACFILTER_EDIT, body)

    @uses(Page.MAC_FILTER, Endpoint.MACFILTER_DELETE)
    async def delete_rule(self, instance: int) -> None:
        """Delete a rule (``instance`` is :attr:`MacFilterRule.instance`)."""
        current = await self.get_settings()
        rule = next((r for r in current.rules if r.instance == instance), None)
        if rule is None:
            invalid(f"no MAC filter rule with instance {instance}")

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "del_instance": rule.instance}

        await self._client._command(Endpoint.MACFILTER_DELETE, body)
