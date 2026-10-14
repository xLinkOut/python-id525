"""adm-sw.html: ask the operator's update server for new firmware (installs nothing)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

INPROGRESS = {"result": "inprogress"}


async def check_for_update(page: BrowserPage, inputs: dict[str, Any]) -> None:
    """Run the "check for update" handler, with the UI's 6 s poll delay shortened.

    This firmware's page disables the button on every load
    (``onScreenWidthChange``), so a user can't start the check: the handler the
    button is wired to, ``check_upgrade()``, is invoked directly. Only the
    timing changes (the capture settles after 1.5 s of silence); the requests
    and their bodies are the UI's.
    """
    del inputs
    await page.evaluate(
        """() => {
            const original = window.setTimeout;
            window.setTimeout = (fn, ms, ...args) =>
                original(fn, ms === 6000 ? 100 : ms, ...args);
        }"""
    )
    await page.evaluate("() => check_upgrade()")


def _check(name: str, answers: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.SOFTWARE,
        endpoint=Endpoint.ACS_CHECK_UPDATE_STATUS,
        call="software.check_for_update",
        inputs={},
        call_kwargs={"poll_interval": 0},
        answers=answers,
        drive=check_for_update,
        **kw,
    )


SCENARIOS = [
    _check(
        "software_check_update_available",
        {
            Endpoint.ACS_CHECK_UPDATE.value: INPROGRESS,
            Endpoint.ACS_CHECK_UPDATE_STATUS.value: [
                INPROGRESS,
                {"result": "ready", "AvailSoftwareVersion": "ID525_REL_1.0.10.01"},
            ],
        },
        notes="check, then poll until ready; nothing is installed",
    ),
    _check(
        "software_check_up_to_date",
        {
            Endpoint.ACS_CHECK_UPDATE.value: INPROGRESS,
            Endpoint.ACS_CHECK_UPDATE_STATUS.value: [
                INPROGRESS,
                INPROGRESS,
                {"result": "ready", "AvailSoftwareVersion": ""},
            ],
        },
    ),
    Scenario(
        name="software_check_ready_at_once",
        page=Page.SOFTWARE,
        endpoint=Endpoint.ACS_CHECK_UPDATE,
        call="software.check_for_update",
        inputs={},
        call_kwargs={"poll_interval": 0},
        answers={
            Endpoint.ACS_CHECK_UPDATE.value: {
                "result": "ready",
                "AvailSoftwareVersion": "ID525_REL_1.0.10.01",
            }
        },
        drive=check_for_update,
        notes="no poll when the first answer is already ready",
    ),
]
