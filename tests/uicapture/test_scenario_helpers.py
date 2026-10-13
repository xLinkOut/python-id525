"""Scenario helpers must only do what a user could do."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.uicapture.browser import guarded_context
from tools.uicapture.mockrouter import MockRouter
from tools.uicapture.scenarios.base import click

pytestmark = pytest.mark.browser

PAGE = """<!doctype html><html><body>
<div class="modal" id="closed">
  <button id="in-closed" onclick="window.hits.push('closed')"></button>
</div>
<div class="modal show" id="open">
  <button id="in-open" onclick="window.hits.push('open')"></button>
</div>
<button id="plain" onclick="window.hits.push('plain')"></button>
<script>window.hits = [];</script></body></html>"""


async def test_click_refuses_buttons_of_unopened_modals(tmp_path: Path) -> None:
    (tmp_path / "modals.html").write_text(PAGE)
    mock = MockRouter(pages_dir=tmp_path, assets_dir=None)
    await mock.start()
    try:
        async with guarded_context(mock.origin) as (context, _):
            page = await context.new_page()
            await page.goto("/cgi-bin/cm/modals.html")
            await click(page, "plain")
            await click(page, "in-open")
            with pytest.raises(LookupError, match="did not open"):
                await click(page, "in-closed")
            with pytest.raises(LookupError, match="no element"):
                await click(page, "nope")
            assert await page.evaluate("window.hits") == ["plain", "open"]
    finally:
        await mock.stop()
