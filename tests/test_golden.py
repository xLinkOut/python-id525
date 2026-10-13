"""The client must send byte-for-byte what the router's own web UI sends.

Each file in ``tests/golden`` was produced by running the router UI code in a
sandboxed browser (``tools/uicapture``) on the same anonymised page fixture the
fake router serves here. The client gets the scenario's inputs and must emit
the identical request body (only the CSRF token value is normalised), or, for
inputs the UI refuses, refuse them too without sending anything.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from id525 import Id525ValidationError
from id525.endpoints import Endpoint, Status

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


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.stem)
async def test_client_matches_ui(
    path: Path, make_client: ClientFactory, router: FakeRouter
) -> None:
    golden = load(path)
    page = FIXTURES / f"{golden['page']}.html"
    assert hashlib.sha256(page.read_bytes()).hexdigest() == golden["fixture_sha256"], (
        "page fixture changed since the capture: re-run tools.uicapture.capture"
    )
    client = await make_client(read_only=False)
    method = resolve(client, golden["call"])
    args = {**golden["inputs"], **golden["call_kwargs"]}

    if golden["refused"]:
        with pytest.raises(Id525ValidationError):
            await method(**args)
        assert golden["endpoint"] not in router.calls
        return

    await method(**args)
    sent = [body for name, body in router.bodies if name == golden["endpoint"]]
    assert len(sent) == 1
    token = json.loads(sent[0])["RequestVerifyToken"]
    assert sent[0].decode().replace(token, TOKEN_PLACEHOLDER) == golden["body"]
    others = [n for n in router.calls if n in MUTATING and n != golden["endpoint"]]
    assert others == []


def test_every_scenario_has_a_golden() -> None:
    from tools.uicapture.scenarios import SCENARIOS

    assert {s.name for s in SCENARIOS} == {p.stem for p in GOLDENS}


def test_ui_captured_status_is_backed_by_goldens() -> None:
    """``ui-captured`` is a claim: it needs at least one golden that sends a body."""
    captured = {load(p)["endpoint"] for p in GOLDENS if not load(p)["refused"]}
    claimed = {e.value for e in Endpoint if e.info.status is Status.UI_CAPTURED}
    assert claimed == captured
