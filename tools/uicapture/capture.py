"""Run the capture scenarios and write the goldens to ``tests/golden/``.

Usage::

    uv run python -m tools.uicapture.capture [--assets DIR] [scenario ...]

``--assets`` (or ``ID525_UI_ASSETS``) is a local copy of the router UI's static
files (``js/``...), e.g. the workspace's ``research/raw``. They are vendor code:
they are read from disk at capture time and never committed. Pages come from
the anonymised fixtures in ``tests/fixtures``.

Offline by construction: the browser can only reach the mock on 127.0.0.1
(see :mod:`tools.uicapture.guard`), and the run aborts if a guard blocked
anything (a sign the page tried to leave the sandbox).
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Kind

from .browser import guarded_context
from .mockrouter import TOKEN_PREFIX, MockRouter, Recorded
from .scenarios import SCENARIOS, Scenario

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext

    from .guard import GuardLog

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
GOLDEN = ROOT / "tests" / "golden"
DEFAULT_ASSETS = ROOT.parent / "research" / "raw"
TOKEN_PLACEHOLDER = "<TOKEN>"  # noqa: S105
FIRST_SEND_TIMEOUT = 5.0
SETTLE = 1.5
"""A flow is over once no new request arrived for this long."""
MAX_FLOW = 30.0
REFUSE_WAIT = 1.5


class CaptureError(RuntimeError):
    """A scenario did not behave as declared."""


def normalise(body: bytes, tokens: list[str]) -> str:
    """Decode a body and replace issued CSRF tokens with a placeholder."""
    text = body.decode("utf-8")
    for token in sorted(tokens, key=len, reverse=True):
        text = text.replace(token, TOKEN_PLACEHOLDER)
    if TOKEN_PREFIX in text:
        msg = f"unknown capture token left in body: {text}"
        raise CaptureError(msg)
    return text


def fixture_digest(fixture: str) -> str:
    """Return the SHA-256 of a page fixture (goldens go stale when it changes)."""
    return hashlib.sha256((FIXTURES / f"{fixture}.html").read_bytes()).hexdigest()


def classify(recorded: list[Recorded]) -> tuple[list[Recorded], list[str]]:
    """Split a flow into mutating requests (compared) and the rest (informative)."""
    mutating, other = [], []
    for request in recorded:
        try:
            kind = Endpoint(request.endpoint).info.kind
        except ValueError:
            msg = f"the UI called {request.endpoint}, which is not in id525.endpoints"
            raise CaptureError(msg) from None
        if kind.mutating:
            mutating.append(request)
        elif kind is not Kind.SESSION and request.endpoint not in other:
            other.append(request.endpoint)  # polls (e.g. SMS at 1 Hz): once, in order
    return mutating, other


async def settle(mock: MockRouter, quiet: float = 0.5, limit: float = 5.0) -> None:
    """Wait until the page made no request for ``quiet`` seconds."""
    started = time.monotonic()
    seen, since = len(mock.requests), time.monotonic()
    while time.monotonic() - started < limit:
        await asyncio.sleep(0.05)
        if len(mock.requests) != seen:
            seen, since = len(mock.requests), time.monotonic()
        elif time.monotonic() - since >= quiet:
            return


async def collect(mock: MockRouter, mark: int, *, refused: bool) -> list[Recorded]:
    """Wait for the flow to finish and return the requests it made."""
    started = time.monotonic()
    if refused:
        await asyncio.sleep(REFUSE_WAIT)
        return mock.requests[mark:]
    # Only mutating requests count as activity: background polls never stop.
    seen, last_change = 0, None
    while time.monotonic() - started < MAX_FLOW:
        mutating, _ = classify(mock.requests[mark:])
        if len(mutating) != seen:
            seen, last_change = len(mutating), time.monotonic()
        if mutating and last_change is not None and time.monotonic() - last_change >= SETTLE:
            break
        if not mutating and time.monotonic() - started > FIRST_SEND_TIMEOUT:
            break
        await asyncio.sleep(0.05)
    return mock.requests[mark:]


async def run_scenario(
    scenario: Scenario, mock: MockRouter, context: BrowserContext, log: GuardLog
) -> dict[str, Any]:
    """Drive one scenario and return its golden record."""
    page = await context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    mock.answers = copy.deepcopy(scenario.answers)
    fixture = scenario.fixture or scenario.page.value
    mock.page_fixtures = {scenario.page.value: fixture}
    try:
        await page.goto(f"/cgi-bin/cm/{scenario.page}.html")
        await page.wait_for_function(
            "() => (document.getElementById('RequestVerifyToken') || {}).value"
            f"?.startsWith('{TOKEN_PREFIX}')"
        )
        # Let the page finish its own load-time calls (e.g. fw-ddns reads its
        # config right after the token arrives) before the flow is recorded.
        await settle(mock)
        mark = len(mock.requests)
        await scenario.drive(page, scenario.inputs)
        flow = await collect(mock, mark, refused=scenario.refused)
        ui_message: str = await page.evaluate(
            "() => (document.getElementById('_dialog_modal_warning') || {}).textContent || ''"
        )
    finally:
        await page.close()
        mock.answers = {}
        mock.page_fixtures = {}

    if log.blocked or log.blocked_websockets:
        msg = f"{scenario.name}: guards blocked {log.blocked + log.blocked_websockets}"
        raise CaptureError(msg)
    mutating, other = classify(flow)
    if scenario.refused and mutating:
        msg = f"{scenario.name}: the UI was expected to refuse but sent {mutating}"
        raise CaptureError(msg)
    if scenario.fixture and scenario.fixture.startswith("synthetic/") and not scenario.synthetic:
        msg = f"{scenario.name}: uses a synthetic fixture, so it must set synthetic=True"
        raise CaptureError(msg)
    if not scenario.refused:
        if scenario.endpoint.value not in [r.endpoint for r in mutating]:
            msg = f"{scenario.name}: no {scenario.endpoint} call; got {mutating} {errors}"
            raise CaptureError(msg)
        bad_type = [r for r in mutating if r.content_type != "application/json"]
        if bad_type:
            msg = f"{scenario.name}: unexpected content type in {bad_type}"
            raise CaptureError(msg)
    return {
        "scenario": scenario.name,
        "page": scenario.page.value,
        "endpoint": scenario.endpoint.value,
        "ui_ref": scenario.endpoint.info.ref,
        "call": scenario.call,
        "inputs": scenario.inputs,
        "call_kwargs": scenario.call_kwargs,
        "answers": scenario.answers,
        "refused": scenario.refused,
        "fixture": fixture,
        "synthetic": scenario.synthetic,
        "requests": [
            {"endpoint": r.endpoint, "body": normalise(r.body, mock.tokens)} for r in mutating
        ],
        "other_calls": other,
        "ui_message": ui_message.strip() if scenario.refused else "",
        "notes": scenario.notes,
        "fixture_sha256": fixture_digest(fixture),
    }


async def capture(scenarios: list[Scenario], assets: Path) -> list[dict[str, Any]]:
    """Run scenarios, each in a fresh guarded browser context."""
    mock = MockRouter(pages_dir=FIXTURES, assets_dir=assets)
    await mock.start()
    records = []
    try:
        for scenario in scenarios:
            async with guarded_context(mock.origin) as (context, log):
                records.append(await run_scenario(scenario, mock, context, log))
    finally:
        await mock.stop()
    return records


def render(record: dict[str, Any]) -> str:
    """Serialise a golden record."""
    return json.dumps(record, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--assets",
        type=Path,
        default=Path(os.environ.get("ID525_UI_ASSETS", DEFAULT_ASSETS)),
        help="local copy of the router UI static files (js/...)",
    )
    parser.add_argument("scenarios", nargs="*", help="scenario names (default: all)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="re-capture and fail if any golden differs (writes nothing)",
    )
    args = parser.parse_args(argv)
    if not (args.assets / "js" / "scriptGeneric.js").is_file():
        print(f"error: no router UI scripts under {args.assets}/js", file=sys.stderr)
        return 2
    by_name = {s.name: s for s in SCENARIOS}
    unknown = set(args.scenarios) - set(by_name)
    if unknown:
        print(f"error: unknown scenarios {sorted(unknown)}", file=sys.stderr)
        return 2
    chosen = [by_name[n] for n in args.scenarios] if args.scenarios else SCENARIOS
    GOLDEN.mkdir(parents=True, exist_ok=True)
    differ = []
    for record in asyncio.run(capture(chosen, args.assets)):
        path = GOLDEN / f"{record['scenario']}.json"
        content = render(record)
        if args.check:
            if not path.exists() or path.read_text() != content:
                differ.append(record["scenario"])
            continue
        path.write_text(content)
        sent = [f"{r['endpoint']} {r['body']}" for r in record["requests"]]
        print(f"{record['scenario']}: {sent or 'refused by the UI'}")
    if args.check:
        print(f"{len(chosen) - len(differ)} goldens identical, {len(differ)} differ: {differ}")
        return 1 if differ else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
