"""The client must send byte-for-byte what the router's own web UI sends.

Each file in ``tests/golden`` was produced by running the router UI code in a
sandboxed browser (``tools/uicapture``) on the same anonymised page fixture the
fake router serves here. The client gets the scenario's inputs and must emit
the identical request body (only the CSRF token value is normalised), or, for
inputs the UI refuses, refuse them too without sending anything.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from id525 import Id525ValidationError
from id525.endpoints import Endpoint, Status
from id525.trace import TraceRecorder

from .conftest import FIXTURES, MUTATING, ClientFactory, FakeRouter

GOLDEN = Path(__file__).parent / "golden"
GOLDENS = sorted(GOLDEN.glob("*.json"))
TOKEN_PLACEHOLDER = "<TOKEN>"


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def resolve(client: object, call: str) -> Any:
    target = client
    for part in call.split("."):
        target = getattr(target, part)
    return target


def normalise(body: bytes) -> str:
    text = body.decode()
    token = json.loads(text).get("RequestVerifyToken")
    return text.replace(token, TOKEN_PLACEHOLDER) if token else text


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.stem)
async def test_client_matches_ui(
    path: Path, make_client: ClientFactory, router: FakeRouter
) -> None:
    golden = load(path)
    page = FIXTURES / f"{golden['fixture']}.html"
    assert hashlib.sha256(page.read_bytes()).hexdigest() == golden["fixture_sha256"], (
        "page fixture changed since the capture: re-run tools.uicapture.capture"
    )
    router.answers = copy.deepcopy(golden["answers"])
    router.page_fixtures = {golden["page"]: golden["fixture"]}
    tracer = TraceRecorder(redact=False)  # tracing must not change a byte
    client = await make_client(read_only=False, tracer=tracer)
    method = resolve(client, golden["call"])
    args = {**golden["inputs"], **golden["call_kwargs"]}

    if golden["refused"]:
        with pytest.raises(Id525ValidationError):
            await method(**args)
        assert not [n for n in router.calls if n in MUTATING]
        return

    await method(**args)
    sent = [
        {"endpoint": name, "body": normalise(body)}
        for name, body in router.bodies
        if name in MUTATING
    ]
    assert sent == golden["requests"]
    traced = [
        (e["path"].removeprefix("/cgi-bin/cgi/").removesuffix(".cgi"), e["request_body"])
        for e in tracer.events
        if e["method"] == "POST"
    ]
    assert traced == [(name, body.decode()) for name, body in router.bodies]


def test_every_scenario_has_a_golden() -> None:
    from tools.uicapture.scenarios import SCENARIOS

    assert {s.name for s in SCENARIOS} == {p.stem for p in GOLDENS}


def test_capture_status_claims_are_backed_by_goldens() -> None:
    """``ui-captured[-synthetic]`` are claims: each needs goldens that send it.

    A captured endpoint later seen on the router becomes ``live-verified``.
    """
    real: set[str] = set()
    synthetic: set[str] = set()
    for path in GOLDENS:
        golden = load(path)
        sent = {r["endpoint"] for r in golden["requests"]}
        (synthetic if golden["synthetic"] else real).update(sent)
    claimed = {e.value for e in Endpoint if e.info.status is Status.UI_CAPTURED}
    claimed_synthetic = {e.value for e in Endpoint if e.info.status is Status.UI_CAPTURED_SYNTHETIC}
    live = {e.value for e in Endpoint if e.info.status is Status.LIVE_VERIFIED}  # a stronger claim
    assert claimed == real - live
    assert claimed_synthetic == synthetic - real - live


def test_synthetic_fixtures_are_up_to_date() -> None:
    from tools.uicapture.synthetic import OUT, render, variants

    for name, variant in variants().items():
        path = OUT / f"{name}.html"
        assert path.exists(), f"run: uv run python -m tools.uicapture.synthetic ({name})"
        assert path.read_text() == render(variant), name
