"""Admin account, session timeout and data usage (``adm-user`` page)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, Page, uses
from ..models import _raw
from ..parsers import (
    clean_str,
    extract_js_values,
    parse_data_gb,
    parse_duration,
    parse_int,
    parse_reset_date,
)
from .base import Section, invalid

if TYPE_CHECKING:
    from collections.abc import Mapping

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 32
SESSION_TIMEOUT_MINUTES = (1, 60)
DATA_LIMIT_RANGE = (1, 999)

# Ported from the web UI (js/validate.js and adm-user.html update_user_pwd()).
_NOT_ALLOWED = "`,\":;&%+'<>?¥" + "￥"  # filed_no_allow_letter + special_symbol
_INVALID_SYMBOL_RE = re.compile(r"['\"`%&+;:,<>?/\\|]")
_DIGIT_RE = re.compile(r"[0-9]")
_LETTER_RE = re.compile(r"[a-zA-Z]")
_SYMBOL_RE = re.compile(r"[!@#$^*()\[\]=_\-.]")
_SESSION_TIMEOUT_RE = re.compile(r"\bvar\s+q_interval\s*=\s*\"(\d+)\"\s*/\s*60")


class DataUnit(StrEnum):
    """Unit of the monthly data-usage limit."""

    GB = "GB"
    MB = "MB"


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountSettings:
    """Account, session and data-usage settings shown by ``adm-user``."""

    username: str | None
    session_timeout: timedelta | None
    """Web session idle timeout (the UI edits it in minutes)."""
    statistics_duration: timedelta | None
    """Time elapsed since the data counters were last reset."""
    statistics_reset_date: date | None
    total_data_gb: float | None
    """Data transferred (TX + RX) since the last reset, in GB (1024 base)."""
    data_limit: int | None
    """Data usage limit (0 = not set)."""
    data_limit_unit: str | None
    raw: Mapping[str, Any] = _raw()


def parse_account_page(html: str) -> AccountSettings:
    """Parse the data the router embeds in ``adm-user.html``."""
    values = extract_js_values(html)
    timeout = _SESSION_TIMEOUT_RE.search(html)
    # The page says e.g. "4477.64 Gbps" and itself rewrites the "bps" suffix to "B".
    total = re.sub(r"bps$", "B", values.get("total_transmit", "").strip())
    return AccountSettings(
        username=clean_str(values.get("input_username") or values.get("username")),
        session_timeout=timedelta(seconds=int(timeout.group(1))) if timeout else None,
        statistics_duration=parse_duration(values.get("duration")),
        statistics_reset_date=parse_reset_date(values.get("reset_date")),
        total_data_gb=parse_data_gb(total),
        data_limit=parse_int(values.get("max_data_amount")),
        data_limit_unit=clean_str(values.get("data_amount_unit")),
        raw=values,
    )


def _check_new_password(password: str, username: str) -> None:
    """Run the checks of the UI's ``update_user_pwd()``, in its order."""
    if any(c in _NOT_ALLOWED for c in password) or not password.isascii():
        invalid(f"the new password must not contain any of {_NOT_ALLOWED[:-1]!r}")
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        invalid(
            f"the new password must be {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters long"
        )
    if any(c in _NOT_ALLOWED for c in username) or not username.isascii():
        invalid(f"the username must not contain any of {_NOT_ALLOWED[:-1]!r}")
    if _INVALID_SYMBOL_RE.search(password):
        invalid("the new password contains a forbidden symbol")
    if not _LETTER_RE.search(password):
        invalid("the new password needs at least one letter")
    if not _DIGIT_RE.search(password):
        invalid("the new password needs at least one digit")
    if not _SYMBOL_RE.search(password):
        invalid("the new password needs at least one of !@#$^*()[]=_-.")


class AccountApi(Section):
    """Admin account, session timeout, data usage."""

    @uses(Page.ACCOUNT)
    async def get_settings(self) -> AccountSettings:
        """Return the account, session-timeout and data-usage settings."""
        return parse_account_page(await self._client._page(Page.ACCOUNT))

    @uses(Page.ACCOUNT, Endpoint.SET_ACCOUNT)
    async def change_password(
        self,
        current_password: str,
        new_password: str,
        *,
        username: str | None = None,
        confirm: bool = False,
    ) -> None:
        """Change the admin password (and optionally the username).

        Destructive: a mistake locks you out of the router, so it needs
        ``confirm=True``. ``username`` defaults to the current one. The client
        uses the new password for its next logins.
        """
        if username is None:
            username = (await self.get_settings()).username or ""
        _check_new_password(new_password, username)

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "username": username,
                "current_pwd": current_password,
                "new_pwd": new_password,
            }

        await self._client._command(Endpoint.SET_ACCOUNT, body, confirmed=confirm)
        # The UI sends the user back to the login page: log in again, with the new password.
        self._client._set_password(new_password)
        self._client._forget_session()

    @uses(Endpoint.SET_DEVICE_MANAGEMENT)
    async def set_session_timeout(self, minutes: int) -> None:
        """Set the web session idle timeout (1-60 minutes)."""
        low, high = SESSION_TIMEOUT_MINUTES
        if not low <= minutes <= high:
            invalid(f"the session timeout must be {low}-{high} minutes")

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "timeout": minutes * 60}

        await self._client._command(Endpoint.SET_DEVICE_MANAGEMENT, body)

    @uses(Endpoint.RESET_DATA)
    async def reset_data_usage(self, *, confirm: bool = False) -> None:
        """Reset the data usage counters. Destructive: needs ``confirm=True``."""
        await self._client._command(
            Endpoint.RESET_DATA, lambda token: {TOKEN_FIELD: token}, confirmed=confirm
        )

    @uses(Endpoint.DATA_USAGE_SAVE)
    async def set_data_limit(self, value: int, unit: DataUnit) -> None:
        """Set the data usage limit (1-999 GB or MB)."""
        low, high = DATA_LIMIT_RANGE
        if not low <= value <= high:
            invalid(f"the data limit must be {low}-{high}")
        unit = DataUnit(unit)

        def body(token: str | None) -> dict[str, Any]:
            # The UI sends the input box text, i.e. a string.
            return {TOKEN_FIELD: token, "data_value": str(value), "data_unit": unit.value}

        await self._client._command(Endpoint.DATA_USAGE_SAVE, body)
