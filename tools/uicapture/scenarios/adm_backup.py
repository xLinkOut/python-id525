"""adm-backup.html: reboot."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage


async def reboot(page: BrowserPage, inputs: dict[str, Any]) -> None:
    del inputs
    await click(page, f"{await platform_prefix(page)}-toggle_reboot_modal_btn")
    await click(page, "confRebootConfirmed_btn")


SCENARIOS = [
    Scenario(
        name="reboot",
        page=Page.BACKUP,
        endpoint=Endpoint.REBOOT,
        call="system.reboot",
        inputs={},
        call_kwargs={"confirm": True},
        drive=reboot,
    ),
]
