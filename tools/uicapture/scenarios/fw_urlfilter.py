"""fw-urlfilter.html: URL filter (the real list is unreadable: edits use a synthetic page)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix, set_value
from .fw_adv import set_checked

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

RULES = "synthetic/fw-urlfilter-rules"


async def _position(page: BrowserPage, instance: str) -> int:
    position: int = await page.evaluate(
        "(instance) => url_array.findIndex((e) => e.instance == instance)", instance
    )
    if position < 0:
        msg = f"no URL rule with instance {instance} on the page"
        raise LookupError(msg)
    return position


async def add_url(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"{await platform_prefix(page)}-addNewBtn")
    await set_value(page, "url_Addr", inputs["url"])
    await click(page, "add_urlfilterBtn")


async def edit_url(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"edit_rule_{await _position(page, inputs['instance']) + 1}")
    await set_value(page, "edit_url_Addr", inputs["url"])
    await click(page, "edit_urlfilterBtn")


async def delete_url(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"deleteItem_{await _position(page, inputs['instance'])}")
    await click(page, "confirm_deleteBtn")


async def save_filter(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    if "enabled" in inputs:
        await set_checked(page, f"{pf}-urlfilter_switch", checked=inputs["enabled"])
    if "mode" in inputs:
        await click(
            page, f"{pf}-filterMode_{'white' if inputs['mode'] == 'whitelist' else 'black'}"
        )
    await click(page, f"{pf}-modal_alertBtn")


def _add(name: str, url: str, **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.URL_FILTER,
        endpoint=Endpoint.URLFILTER_ADD,
        call="url_filter.add_url",
        inputs={"url": url},
        drive=add_url,
        **kw,
    )


def _edit(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.URL_FILTER,
        endpoint=Endpoint.URLFILTER_EDIT,
        call="url_filter.edit_url",
        inputs=inputs,
        drive=edit_url,
        fixture=RULES,
        synthetic=True,
        **kw,
    )


def _save(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.URL_FILTER,
        endpoint=Endpoint.URLFILTER_STATUS,
        call="url_filter.set_filter",
        inputs=inputs,
        drive=save_filter,
        **kw,
    )


SCENARIOS = [
    _add("urlfilter_add", "example.com"),
    _add("urlfilter_add_http_path", "https://www.example.org/path_(1)/x~y=z#top"),
    _add("urlfilter_add_refused_empty", "", refused=True),
    _add("urlfilter_add_refused_length", "a" * 124 + ".com", refused=True),
    _add("urlfilter_add_refused_invalid", "not a url", refused=True),
    _add(
        "urlfilter_add_refused_symbol",
        "example.com/a?b=1",
        refused=True,
        notes="passes validateURL, fails isValidURLStr ('?')",
    ),
    _add(
        "urlfilter_add_refused_duplicate",
        "ads.example.net",
        refused=True,
        fixture=RULES,
        synthetic=True,
    ),
    _edit("urlfilter_edit", {"instance": "5", "url": "ads2.example.net"}),
    _edit("urlfilter_edit_http", {"instance": "9", "url": "http://tracker.example.org/new"}),
    _edit(
        "urlfilter_edit_refused_same",
        {"instance": "3", "url": "example.com"},
        refused=True,
        notes="the UI counts the rule's own URL as a duplicate",
    ),
    Scenario(
        name="urlfilter_delete",
        page=Page.URL_FILTER,
        endpoint=Endpoint.URLFILTER_DELETE,
        call="url_filter.delete_url",
        inputs={"instance": "9"},
        drive=delete_url,
        fixture=RULES,
        synthetic=True,
    ),
    _save("urlfilter_enable_whitelist", {"enabled": True, "mode": "whitelist"}),
    _save("urlfilter_save_unchanged", {}),
    _save(
        "urlfilter_disable_keep_mode",
        {"enabled": False},
        fixture=RULES,
        synthetic=True,
        notes="page has the filter on in whitelist mode",
    ),
]
