from __future__ import annotations

import math

import pytest

from id525 import Id525ValidationError
from id525.sections.sms import _Conversations, js_number

from .conftest import ClientFactory, FakeRouter


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("+390000000001", 390000000001.0),
        (" 12 ", 12.0),
        ("", 0.0),
        (None, 0.0),
        (7, 7.0),
        ("0x1f", 31.0),
        ("1e3", 1000.0),
        ("-Infinity", -math.inf),
    ],
)
def test_js_number(value: object, expected: float) -> None:
    assert js_number(value) == expected


@pytest.mark.parametrize("value", ["2026/10/01 08:15:00", "TIM", "1_000", "nan", "inf"])
def test_js_number_nan(value: str) -> None:
    assert math.isnan(js_number(value))


def test_conversations_follow_the_ui() -> None:
    store = [
        {"index": 1, "phone_number": "+3901", "read_status": 1},
        {"index": 2, "phone_number": "+3902", "read_status": 0},
        {"index": 3, "phone_number": "+3901", "read_status": 0},
        {"index": 4, "phone_number": "+3902", "read_status": "0"},
    ]
    conversations = _Conversations(store)
    # numeric descending on phone_number, stable inside a number
    assert [m["index"] for m in conversations.messages] == [2, 4, 1, 3]
    assert [m["index"] for m in conversations.latest] == [4, 3]
    assert conversations.latest[0]["unread_num"] == 2  # "0" == 0 in JS
    assert list(conversations.latest[1])[-3:] == ["unread_num", "Class", "onCheck"]
    assert "unread_num" not in conversations.messages[0]


async def test_mark_read_without_unread_sends_nothing(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(read_only=False)
    await client.sms.mark_read("+390000000002")  # already read in the fixture
    assert "req_smsUpdateStatus" not in router.calls


async def test_unknown_conversation(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match="no SMS conversation"):
        await client.sms.delete_conversations(["+390000000099"])
    with pytest.raises(Id525ValidationError, match="no conversation selected"):
        await client.sms.delete_conversations([])
    assert "req_smsDelete" not in router.calls


async def test_send_accepts_a_list(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client(read_only=False)
    await client.sms.send(["+390000000001", "123"], "hi")
    assert router.bodies[-1][1].endswith(
        b'"Recipients":"+390000000001,123","RecipientsNum":2,"SMScontext":"hi"}'
    )
    with pytest.raises(Id525ValidationError):
        await client.sms.send(["12 34"], "hi")
