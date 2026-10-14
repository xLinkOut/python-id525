"""fw-macfilter.html: MAC filter switch / mode and rules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix, set_value

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

RULES = "synthetic/fw-macfilter-rules"


async def _set_switch(page: BrowserPage, element_id: str, *, checked: bool) -> None:
    await page.evaluate(
        """([id, checked]) => {
            const el = document.getElementById(id);
            el.checked = checked;
            el.dispatchEvent(new Event("change", {bubbles: true}));
        }""",
        [element_id, checked],
    )


async def _modal_open(page: BrowserPage, element_id: str) -> bool:
    is_open: bool = await page.evaluate(
        "(id) => document.getElementById(id).classList.contains('show')", element_id
    )
    return is_open


async def save_status(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    enabled = inputs["_enabled"]
    await _set_switch(page, f"{pf}-macfilter_switch", checked=enabled)
    if inputs.get("mode") == "whitelist":
        await click(page, f"{pf}-filterMode_white")
    elif inputs.get("mode") == "blacklist":
        await click(page, f"{pf}-filterMode_black")
    await click(page, f"{pf}-save_status")
    if enabled and await _modal_open(page, "modal_filter_status"):
        await click(page, "inModal_Btn_toggle_status_save")  # "turn on?" confirmation


async def add_new(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"{await platform_prefix(page)}-addNewBtn")
    await click(page, "select_AddNew")
    await set_value(page, "device_input", inputs["name"])
    await set_value(page, "mac_input", inputs["mac"])
    await click(page, "add_ruleBtn")


async def add_from_available(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"{await platform_prefix(page)}-addNewBtn")
    await click(page, "select_FromAvailable")
    await page.evaluate(
        """(mac) => {
            const sel = document.getElementById("maclist_select");
            sel.selectedIndex = [...sel.options].findIndex((o) => o.text.toLowerCase() == mac);
            sel.dispatchEvent(new Event("change", {bubbles: true}));
        }""",
        inputs["mac"].lower(),
    )
    await click(page, "add_ruleBtn")


async def add_from_client_list(page: BrowserPage, inputs: dict[str, Any]) -> None:
    position: int = await page.evaluate(
        "(mac) => client_list_entries.client_list.findIndex((c) => c.mac.toLowerCase() == mac)",
        inputs["mac"].lower(),
    )
    await click(page, f"add_connected_{position}")
    await click(page, "inModal_Btn_add_connected_save")


async def _rule_position(page: BrowserPage, instance: int) -> int:
    position: int = await page.evaluate(
        "(instance) => mac_array.findIndex((r) => r.instance == instance)", instance
    )
    if position < 0:
        msg = f"no rule with instance {instance} on the page"
        raise LookupError(msg)
    return position


async def edit_rule(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"edit_rule_{await _rule_position(page, inputs['instance'])}")
    if "name" in inputs:
        await set_value(page, "edit_device_input", inputs["name"])
    if "mac" in inputs:
        await set_value(page, "edit_mac_input", inputs["mac"])
    await click(page, "inModal_Btn_edit_rule_save")


async def delete_rule(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"delete_rule_{await _rule_position(page, inputs['instance'])}")
    await click(page, "inModal_Btn_delete_rule_save")


async def enable(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await save_status(page, {**inputs, "_enabled": True})


async def disable(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await save_status(page, {**inputs, "_enabled": False})


def _s(
    name: str,
    endpoint: Endpoint,
    call: str,
    inputs: dict[str, Any],
    drive: Any,
    *,
    synthetic: bool = False,
    **kw: Any,
) -> Scenario:
    return Scenario(
        name=name,
        page=Page.MAC_FILTER,
        endpoint=endpoint,
        call=f"mac_filter.{call}",
        inputs=inputs,
        drive=drive,
        fixture=RULES if synthetic else None,
        synthetic=synthetic,
        **kw,
    )


_SAVE, _ADD = Endpoint.MACFILTER_SAVE, Endpoint.MACFILTER_ADD
_EDIT, _DEL = Endpoint.MACFILTER_EDIT, Endpoint.MACFILTER_DELETE

SCENARIOS = [
    _s("macfilter_enable_blacklist", _SAVE, "enable", {"mode": "blacklist"}, enable),
    _s(
        "macfilter_enable_current_mode",
        _SAVE,
        "enable",
        {},
        enable,
        notes="mode left alone: the page's current mode (blacklist) is sent",
    ),
    _s("macfilter_disable", _SAVE, "disable", {}, disable),
    _s(
        "macfilter_enable_whitelist_refused_no_rules",
        _SAVE,
        "enable",
        {"mode": "whitelist"},
        enable,
        refused=True,
        notes="a whitelist without rules would lock every device out",
    ),
    _s(
        "macfilter_enable_whitelist",
        _SAVE,
        "enable",
        {"mode": "whitelist"},
        enable,
        synthetic=True,
    ),
    _s(
        "macfilter_add",
        _ADD,
        "add_rule",
        {"mac": "02:00:5E:00:02:AA", "name": "printer-2.lan"},
        add_new,
    ),
    _s(
        "macfilter_add_lowercase",
        _ADD,
        "add_rule",
        {"mac": "02:00:5e:00:02:ab", "name": "TV"},
        add_new,
    ),
    _s(
        "macfilter_add_refused_empty_name",
        _ADD,
        "add_rule",
        {"mac": "02:00:5e:00:02:ac", "name": ""},
        add_new,
        refused=True,
    ),
    _s(
        "macfilter_add_refused_empty_mac",
        _ADD,
        "add_rule",
        {"mac": "", "name": "nas"},
        add_new,
        refused=True,
    ),
    _s(
        "macfilter_add_refused_bad_mac",
        _ADD,
        "add_rule",
        {"mac": "02-00-5e-00-02-ac", "name": "nas"},
        add_new,
        refused=True,
    ),
    _s(
        "macfilter_add_refused_name_charset",
        _ADD,
        "add_rule",
        {"mac": "02:00:5e:00:02:ac", "name": "tv salotto"},
        add_new,
        refused=True,
        notes="only letters, digits, '-' and '.' (no spaces, no '_')",
    ),
    _s(
        "macfilter_add_refused_long_name",
        _ADD,
        "add_rule",
        {"mac": "02:00:5e:00:02:ac", "name": "n" * 33},
        add_new,
        refused=True,
    ),
    _s(
        "macfilter_add_refused_duplicate_mac",
        _ADD,
        "add_rule",
        {"mac": "02:00:5e:00:01:0A", "name": "nas"},
        add_new,
        synthetic=True,
        refused=True,
        notes="duplicate check is case-insensitive",
    ),
    _s(
        "macfilter_add_from_available",
        _ADD,
        "add_connected_client",
        {"mac": "02:00:5e:00:00:04"},
        add_from_available,
        notes="'Add New' dialog, 'From Available' list",
    ),
    _s(
        "macfilter_add_from_client_list",
        _ADD,
        "add_connected_client",
        {"mac": "02:00:5e:00:00:05"},
        add_from_client_list,
        notes="'+' button of the connected-client table",
    ),
    _s(
        "macfilter_add_from_client_list_refused_duplicate",
        _ADD,
        "add_connected_client",
        {"mac": "02:00:5e:00:00:06"},
        add_from_client_list,
        synthetic=True,
        refused=True,
        notes="host-04 is already a rule (stored in upper case)",
    ),
    _s(
        "macfilter_edit",
        _EDIT,
        "modify_rule",
        {"instance": 2, "name": "tablet-2", "mac": "02:00:5e:00:01:0c"},
        edit_rule,
        synthetic=True,
    ),
    _s(
        "macfilter_edit_mac_only",
        _EDIT,
        "modify_rule",
        {"instance": 6, "mac": "02:00:5E:00:01:0D"},
        edit_rule,
        synthetic=True,
    ),
    _s(
        "macfilter_edit_refused_same_mac",
        _EDIT,
        "modify_rule",
        {"instance": 2, "name": "tablet-3"},
        edit_rule,
        synthetic=True,
        refused=True,
        notes="UI quirk: the edited rule's own MAC counts as a duplicate",
    ),
    _s("macfilter_delete", _DEL, "delete_rule", {"instance": 6}, delete_rule, synthetic=True),
]
