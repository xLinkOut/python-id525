"""SMS management (``adm-sms`` page): mark read, delete, send.

Reading the SMS store is :meth:`id525.Id525Client.get_sms`. The operations
here work on *conversations* (all messages of one phone number), like the UI,
and rebuild the UI's own view of the store first: the delete request carries
the message objects exactly as the UI holds them, including the bookkeeping
fields it adds to the latest message of each conversation.
"""

from __future__ import annotations

import functools
import math
import re
from typing import Any

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, uses
from .base import Section, invalid

_PHONE_RE = re.compile(r"^[\+]?[0-9]{1,15}$", re.MULTILINE)  # validatePhoneNum
_JS_DECIMAL_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_RECIPIENT_SEPARATOR = ", "  # the UI splits the recipients box on ", "


def js_number(value: Any) -> float:  # noqa: PLR0911
    """JavaScript ``Number(value)`` for the JSON types the router returns."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if value is None:
        return 0.0
    if not isinstance(value, str):
        return math.nan
    text = value.strip()
    if not text:
        return 0.0
    if _JS_DECIMAL_RE.match(text):
        return float(text)
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", text):
        return float(int(text, 16))
    if text.lstrip("+-") == "Infinity":
        return -math.inf if text.startswith("-") else math.inf
    return math.nan


def _js_is_zero(value: Any) -> bool:
    """JavaScript ``value == 0``."""
    return value is not None and js_number(value) == 0


def _js_string(value: Any) -> str:
    """JavaScript ``String(value)`` for numbers and strings."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _descending(key: str) -> Any:
    """Sort key for the comparator ``(a, b) => b[key] - a[key]`` (NaN = equal, like JS)."""

    def compare(a: dict[str, Any], b: dict[str, Any]) -> int:
        diff = js_number(b.get(key)) - js_number(a.get(key))
        return 0 if math.isnan(diff) else (diff > 0) - (diff < 0)

    return functools.cmp_to_key(compare)


class _Conversations:
    """Port of the UI's ``initSMS_json_data()``: the store grouped by phone number."""

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        data = sorted(messages, key=_descending("time"))
        data = sorted(data, key=_descending("phone_number"))
        self.messages = data
        self.latest: list[dict[str, Any]] = []
        """The latest message of each conversation, in the UI's display order."""
        self.by_class: dict[str, list[dict[str, Any]]] = {}
        if not data:
            return
        phone = data[0].get("phone_number")
        for i, message in enumerate(data):
            if phone != message.get("phone_number"):
                phone = message.get("phone_number")
                self._remember(data[i - 1])
        self._remember(data[-1])
        for last in self.latest:
            key = last.get("phone_number")
            group = [m for m in data if m.get("phone_number") == key]
            self.by_class[_js_string(key)] = group
            last["unread_num"] = sum(1 for m in group if _js_is_zero(m.get("read_status")))
            last["Class"] = key
            last["onCheck"] = False

    def _remember(self, message: dict[str, Any]) -> None:
        for i, last in enumerate(self.latest):
            if last.get("phone_number") == message.get("phone_number"):
                self.latest[i] = message
                return
        self.latest.append(message)

    def conversation(self, phone_number: str) -> list[dict[str, Any]]:
        group = self.by_class.get(phone_number)
        if not group:
            invalid(f"no SMS conversation with {phone_number}")
        return group


def _split(numbers: str | list[str]) -> list[str]:
    return numbers.split(_RECIPIENT_SEPARATOR) if isinstance(numbers, str) else list(numbers)


class SmsApi(Section):
    """SMS management: mark read, delete conversations, send."""

    async def _conversations(self) -> _Conversations:
        data = await self._client._call(Endpoint.SMS_LIST)
        messages = data.get("message")
        return _Conversations([m for m in messages if isinstance(m, dict)] if messages else [])

    @uses(Endpoint.SMS_LIST, Endpoint.SMS_UPDATE_STATUS)
    async def mark_read(self, phone_number: str) -> None:
        """Mark every unread message from ``phone_number`` as read (opening the chat in the UI).

        Sends nothing if the conversation has no unread message.
        """
        conversations = await self._conversations()
        chat = conversations.conversation(phone_number)
        if not js_number(chat[-1].get("unread_num")) > 0:
            return
        indexes = [m.get("index") for m in chat if _js_is_zero(m.get("read_status"))]

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "list_length": len(indexes),
                "index_List": ",".join(_js_string(i) for i in indexes),
            }

        await self._client._command(Endpoint.SMS_UPDATE_STATUS, body)

    @uses(Endpoint.SMS_LIST, Endpoint.SMS_DELETE)
    async def delete_conversations(self, phone_numbers: str | list[str]) -> None:
        """Delete every message of the given conversations (a list, or ``"a, b"``)."""
        selected = _split(phone_numbers)
        if not selected:
            invalid("no conversation selected")
        conversations = await self._conversations()
        for number in selected:
            conversations.conversation(number)
            for last in conversations.latest:
                if last.get("phone_number") == number:
                    last["onCheck"] = True
        doomed = [
            message
            for last in conversations.latest
            if last["onCheck"]
            for message in conversations.by_class[_js_string(last["Class"])]
        ]

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "DeleteSMS_List": doomed}

        await self._client._command(Endpoint.SMS_DELETE, body)

    @uses(Endpoint.SMS_COMPOSE)
    async def send(self, recipients: str | list[str], text: str) -> None:
        """Send an SMS (costs money!) to one or more numbers (a list, or ``"a, b"``)."""
        numbers = _split(recipients)
        if not numbers or not all(_PHONE_RE.search(n) for n in numbers):
            invalid(f"invalid recipient in {numbers!r}: up to 15 digits, optional leading +")
        if not text:
            invalid("the message is empty")

        def body(token: str | None) -> dict[str, Any]:
            return {
                TOKEN_FIELD: token,
                "Recipients": ",".join(numbers),
                "RecipientsNum": len(numbers),
                "SMScontext": text,
            }

        await self._client._command(Endpoint.SMS_COMPOSE, body)
