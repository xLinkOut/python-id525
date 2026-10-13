"""Scenario model and DOM helpers shared by all pages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from playwright.async_api import Page as BrowserPage

    from id525.endpoints import Endpoint, Page

    type Driver = Callable[[BrowserPage, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class Scenario:
    """One user interaction in the router UI, and the client call equivalent to it.

    ``drive`` performs the interaction in the browser; ``call`` names the client
    method (``"section.method"``) that must send the very same request when
    given ``inputs``. With ``refused=True`` the UI must refuse to send anything
    (client-side validation) and the client must raise ``Id525ValidationError``.
    """

    name: str
    page: Page
    endpoint: Endpoint
    call: str
    inputs: dict[str, Any]
    drive: Driver
    refused: bool = False
    notes: str = ""
    call_kwargs: dict[str, Any] = field(default_factory=dict)
    """Extra arguments for the client call only (e.g. ``confirm=True``)."""


async def set_value(page: BrowserPage, element_id: str, value: str) -> None:
    """Type a value into an input like a user would (fires input/change/keyup)."""
    await page.evaluate(
        """([id, value]) => {
            const el = document.getElementById(id);
            if (!el) throw new Error("no element #" + id);
            el.value = value;
            for (const type of ["input", "keyup", "change"]) {
                el.dispatchEvent(new Event(type, {bubbles: true}));
            }
        }""",
        [element_id, value],
    )


async def click(page: BrowserPage, element_id: str) -> None:
    """Click an element even inside a closed modal (the shims don't render modals)."""
    found = await page.evaluate(
        """(id) => {
            const el = document.getElementById(id);
            if (!el) return false;
            el.click();
            return true;
        }""",
        element_id,
    )
    if not found:
        msg = f"no element #{element_id}"
        raise LookupError(msg)


async def platform_prefix(page: BrowserPage) -> str:
    """Return the UI's responsive-layout id prefix (``xxl``/``xl``/``mobile``)."""
    prefix: str = await page.evaluate(
        "window.innerWidth >= 1400 ? 'xxl' : (window.innerWidth >= 576 ? 'xl' : 'mobile')"
    )
    return prefix
