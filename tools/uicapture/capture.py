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
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .browser import guarded_context
from .mockrouter import TOKEN_PREFIX, MockRouter
from .scenarios import SCENARIOS, Scenario

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext

    from .guard import GuardLog

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
GOLDEN = ROOT / "tests" / "golden"
DEFAULT_ASSETS = ROOT.parent / "research" / "raw"
BACKGROUND = {"token_query", "login_query"}
"""Calls the UI makes on its own (page load, session watchdog)."""
TOKEN_PLACEHOLDER = "<TOKEN>"  # noqa: S105
SEND_TIMEOUT = 5.0
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


def fixture_digest(page: str) -> str:
    """Return the SHA-256 of a page fixture (goldens go stale when it changes)."""
    return hashlib.sha256((FIXTURES / f"{page}.html").read_bytes()).hexdigest()


async def run_scenario(
    scenario: Scenario, mock: MockRouter, context: BrowserContext, log: GuardLog
) -> dict[str, Any]:
    """Drive one scenario and return its golden record."""
    page = await context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    try:
        await page.goto(f"/cgi-bin/cm/{scenario.page}.html")
        await page.wait_for_function(
            "() => (document.getElementById('RequestVerifyToken') || {}).value"
            f"?.startsWith('{TOKEN_PREFIX}')"
        )
        mark = len(mock.requests)
        await scenario.drive(page, scenario.inputs)
        deadline = time.monotonic() + (REFUSE_WAIT if scenario.refused else SEND_TIMEOUT)
        sent = []
        while time.monotonic() < deadline:
            sent = [r for r in mock.requests[mark:] if r.endpoint not in BACKGROUND]
            if sent and not scenario.refused:
                break
            await asyncio.sleep(0.05)
        ui_message: str = await page.evaluate(
            "() => (document.getElementById('_dialog_modal_warning') || {}).textContent || ''"
        )
    finally:
        await page.close()

    if log.blocked or log.blocked_websockets:
        msg = f"{scenario.name}: guards blocked {log.blocked + log.blocked_websockets}"
        raise CaptureError(msg)
    if scenario.refused:
        if sent:
            msg = f"{scenario.name}: the UI was expected to refuse but sent {sent}"
            raise CaptureError(msg)
        body = None
    else:
        if [r.endpoint for r in sent] != [scenario.endpoint.value]:
            msg = f"{scenario.name}: expected one {scenario.endpoint} call, got {sent} {errors}"
            raise CaptureError(msg)
        if sent[0].content_type != "application/json":
            msg = f"{scenario.name}: unexpected content type {sent[0].content_type}"
            raise CaptureError(msg)
        body = normalise(sent[0].body, mock.tokens)
    return {
        "scenario": scenario.name,
        "page": scenario.page.value,
        "endpoint": scenario.endpoint.value,
        "ui_ref": scenario.endpoint.info.ref,
        "call": scenario.call,
        "inputs": scenario.inputs,
        "call_kwargs": scenario.call_kwargs,
        "refused": scenario.refused,
        "body": body,
        "ui_message": ui_message.strip() if scenario.refused else "",
        "notes": scenario.notes,
        "fixture_sha256": fixture_digest(scenario.page.value),
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
    for record in asyncio.run(capture(chosen, args.assets)):
        path = GOLDEN / f"{record['scenario']}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        print(f"{record['scenario']}: {record['body'] or 'refused by the UI'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
