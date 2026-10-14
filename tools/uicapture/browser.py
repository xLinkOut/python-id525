"""A headless Chromium wired to the guards (see :mod:`.guard`)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from playwright.async_api import async_playwright

from .guard import LAUNCH_ARGS, GuardLog, install_guards

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from playwright.async_api import BrowserContext


@asynccontextmanager
async def guarded_context(
    allowed_origin: str, *, routing: bool = True
) -> AsyncIterator[tuple[BrowserContext, GuardLog]]:
    """Yield a browser context that can only reach ``allowed_origin``.

    ``routing=False`` disables layer 1 (request routing) and exists only so the
    test suite can prove that the proxy layer holds on its own.
    """
    log = GuardLog()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=list(LAUNCH_ARGS))
        try:
            context = await browser.new_context(
                service_workers="block", accept_downloads=False, base_url=allowed_origin
            )
            if routing:
                await install_guards(context, allowed_origin, log)
            context.on("page", lambda page: page.on("dialog", lambda d: d.accept()))
            yield context, log
        finally:
            await browser.close()
