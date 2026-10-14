"""adm-sms.html: mark read, delete conversations, send.

The page embeds no messages: it polls ``req_smsReload`` every second. The
scenarios answer it with ``tests/fixtures/sms_reload.json`` (invented
messages), which the test suite's fake router also serves, so the UI and the
client act on the same store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix, set_value

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

_STORE = json.loads(
    (Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sms_reload.json").read_text()
)
_STORE.pop("result", None)
STORE_ANSWERS = {Endpoint.SMS_LIST.value: _STORE}
EMPTY_STORE = {Endpoint.SMS_LIST.value: {"sms_update_time": "1", "message": []}}


async def _wait_for_store(page: BrowserPage) -> None:
    await page.wait_for_function("() => message_search_array.length > 0")


async def _row(page: BrowserPage, phone_number: str) -> int:
    row: int = await page.evaluate(
        "(phone) => message_search_array.findIndex((m) => m.phone_number == phone)", phone_number
    )
    if row < 0:
        msg = f"no conversation with {phone_number} on the page"
        raise LookupError(msg)
    return row


async def open_and_close_chat(page: BrowserPage, inputs: dict[str, Any]) -> None:
    """Open the conversation (which marks it read) and close it in the same tick.

    With the chat open, the UI repeats the update on every 1 s reload while the
    store still says "unread"; a real router flips the status after the first
    one. Closing at once keeps the capture to the single request a user sends.
    """
    await _wait_for_store(page)
    row = await _row(page, inputs["phone_number"])
    await page.evaluate(
        """(row) => {
            showChatScreen(row);
            bootstrap.Modal.getOrCreateInstance(
                document.getElementById('_sendChat_dialog_modal')).hide();
        }""",
        row,
    )


async def delete_conversations(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await _wait_for_store(page)
    pf = await platform_prefix(page)
    for number in inputs["phone_numbers"]:
        await click(page, f"{pf}-contactCheckbox{await _row(page, number)}")
    await click(page, f"{pf}-DeleteBtn")
    await click(page, "_dialog_modal_Btn")  # the confirmation dialog's "Delete"


async def compose(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"{await platform_prefix(page)}-ComposeBtn")
    await set_value(page, "RecipientsInput", inputs["recipients"])
    await set_value(page, "ComposeTextarea", inputs["text"])
    await click(page, "_SendToUser_Btn")


async def reply_in_chat(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await _wait_for_store(page)
    (number,) = inputs["recipients"]
    await page.evaluate("(row) => showChatScreen(row)", await _row(page, number))
    await set_value(page, "chatTextarea", inputs["text"])
    await click(page, "_SendChat_Btn")


def _compose(name: str, recipients: str, text: str, **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.SMS,
        endpoint=Endpoint.SMS_COMPOSE,
        call="sms.send",
        inputs={"recipients": recipients, "text": text},
        answers=EMPTY_STORE,
        drive=compose,
        **kw,
    )


SCENARIOS = [
    Scenario(
        name="sms_mark_read",
        page=Page.SMS,
        endpoint=Endpoint.SMS_UPDATE_STATUS,
        call="sms.mark_read",
        inputs={"phone_number": "+390000000001"},
        answers=STORE_ANSWERS,
        synthetic=True,
        drive=open_and_close_chat,
        notes="index_List is a comma-joined string, list_length a number",
    ),
    Scenario(
        name="sms_delete_one",
        page=Page.SMS,
        endpoint=Endpoint.SMS_DELETE,
        call="sms.delete_conversations",
        inputs={"phone_numbers": ["+390000000002"]},
        answers=STORE_ANSWERS,
        synthetic=True,
        drive=delete_conversations,
        notes="the UI sends whole message objects plus its own unread_num/Class/onCheck",
    ),
    Scenario(
        name="sms_delete_two",
        page=Page.SMS,
        endpoint=Endpoint.SMS_DELETE,
        call="sms.delete_conversations",
        inputs={"phone_numbers": ["+390000000001", "+390000000003"]},
        answers=STORE_ANSWERS,
        synthetic=True,
        drive=delete_conversations,
        notes="conversations are sent in the UI's display order, not the selection order",
    ),
    _compose("sms_send", "+390000000009", 'Ciao! Prova & 100% "ok" — àèì'),
    _compose(
        "sms_send_two_recipients",
        "+390000000008, 3330000000",
        "two lines\nsecond",
        notes="the UI splits the recipients box on ', ' and re-joins with ','",
    ),
    _compose("sms_send_refused_no_recipient", "", "hello", refused=True),
    _compose("sms_send_refused_bad_number", "+39 000", "hello", refused=True),
    _compose("sms_send_refused_too_long_number", "+3900000000000000", "hello", refused=True),
    _compose("sms_send_refused_bad_separator", "+390000000008,3330000000", "hi", refused=True),
    _compose("sms_send_refused_empty_text", "+390000000009", "", refused=True),
    Scenario(
        name="sms_reply_in_chat",
        page=Page.SMS,
        endpoint=Endpoint.SMS_COMPOSE,
        call="sms.send",
        inputs={"recipients": ["+390000000002"], "text": "risposta dalla chat"},
        answers=STORE_ANSWERS,
        synthetic=True,
        drive=reply_in_chat,
        notes="replying in a conversation sends the same request as composing",
    ),
]
