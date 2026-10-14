"""cellular-settings.html: network mode, roaming, operation mode, operators, APNs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix, set_value

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

FIVE_APNS = "synthetic/cellular-settings-5-apns"
_AUTH_IDS = {"NONE": "NONE", "PAP": "PAP", "CHAP": "CHAP", "PAPCHAP": "PAPCHAP"}
_IP_IDS = {"ipv4": "IPv4", "ipv6": "IPv6", "ipv4v6": "IPv4v6"}
# scan_network: mcc,mnc,status,name,type,mnc_includes_pcs_digit; status bits as
# decoded by the UI: 32|1|64 = current serving, 32|2 = available, 16|2 = forbidden.
SCAN = "222,1,97,TIM,12,0;222,10,34,vodafone IT,8,0;222,88,18,WINDTRE,8,0;"
SCAN_3DIGIT = "222,1,97,TIM,12,0;310,410,34,AT&T US,12,1;"


async def set_checked(page: BrowserPage, element_id: str, *, checked: bool) -> None:
    """Set a checkbox and fire ``change``."""
    await page.evaluate(
        """([id, checked]) => {
            const el = document.getElementById(id);
            if (!el) throw new Error("no element #" + id);
            el.checked = checked;
            el.dispatchEvent(new Event("change", {bubbles: true}));
        }""",
        [element_id, checked],
    )


async def _apn_position(page: BrowserPage, instance: int) -> int:
    position: int = await page.evaluate(
        "(instance) => apnJsonList.findIndex((e) => e.instance == instance)", instance
    )
    if position < 0:
        msg = f"no APN with instance {instance} on the page"
        raise LookupError(msg)
    return position


async def network_mode(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    position: int = await page.evaluate("(mode) => mode_list.indexOf(mode)", inputs["mode"])
    await click(page, f"{pf}ModeSelectLi{position}")
    await click(page, f"{pf}-cellularNetworkModeSaveBtn")


async def roaming(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    for _ in range(inputs.get("clicks", 1)):
        await click(page, f"{pf}-RoamingCheckBox")
    await click(page, f"{pf}-roamingSaveBtn")


async def operation_mode(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    item = "OP_Bridge" if inputs["mode"] == "Bridge" else "OP_Routing"
    await click(page, f"{pf}-{item}")
    await click(page, f"{pf}-cellularOperationSaveBtn")


async def search(page: BrowserPage, inputs: dict[str, Any]) -> None:
    del inputs
    await click(page, f"{await platform_prefix(page)}-cellularNetworkModeScanBtn")


async def register(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await search(page, inputs)
    await page.wait_for_function("() => typeof scan_network === 'string' && scan_network.length")
    position: int = await page.evaluate(
        """([mcc, mnc]) => String(scan_network).split(';')
            .findIndex((e) => { const d = e.split(','); return d[0] == mcc && d[1] == mnc; })""",
        [inputs["mcc"], inputs["mnc"]],
    )
    await page.wait_for_selector(f"#Regbtn{position}", state="attached")
    await click(page, f"Regbtn{position}")


async def default_apn(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    fields = (
        ("profile_name", "cellularApnProfileText"),
        ("apn", "cellularApnNameText"),
        ("username", "cellularApnUsernameText"),
        ("password", "cellularApnPasswordText"),
    )
    for key, element in fields:
        if key in inputs:
            await set_value(page, f"{pf}-{element}", inputs[key])
    if "auth" in inputs:
        await click(page, f"{pf}-ApnAuth_{_AUTH_IDS[inputs['auth']]}")
    if "ip_type" in inputs:
        await click(page, f"{pf}-ConType_{_IP_IDS[inputs['ip_type']]}")
    await click(page, f"{pf}-cellularApnSaveBtn")


async def is_shown(page: BrowserPage, element_id: str) -> bool:
    """Return True if a modal is open (a user can only use the buttons inside it then)."""
    shown: bool = await page.evaluate(
        "(id) => document.getElementById(id).classList.contains('show')", element_id
    )
    return shown


async def add_apn(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"{await platform_prefix(page)}-cellularApnAddBtn")
    if not await is_shown(page, "_AddApn_modal"):
        return  # the UI refused to open the dialog (e.g. 5 profiles already)
    await set_value(page, "_AddApnProfileText", inputs.get("profile_name", ""))
    await set_value(page, "addApnNameText", inputs["apn"])
    await set_value(page, "_AddApnUsernameText", inputs.get("username", ""))
    await set_value(page, "_AddApnPasswordText", inputs.get("password", ""))
    if "auth" in inputs:
        await click(page, f"inModalAddApnAuth_{_AUTH_IDS[inputs['auth']]}")
    if "ip_type" in inputs:
        await click(page, f"inModalAddConType_{_IP_IDS[inputs['ip_type']]}")
    if "enabled" in inputs:
        await set_checked(page, "_AddApnStatusCheckBox", checked=inputs["enabled"])
    await click(page, "_AddApn_modal_btn")


async def edit_apn(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"ApnEditBtn{await _apn_position(page, inputs['instance'])}")
    if not await is_shown(page, "_EditApn_modal"):
        return
    fields = (
        ("profile_name", "_EditApnProfileText"),
        ("apn", "_EditApnNameText"),
        ("username", "_EditApnUsernameText"),
        ("password", "_EditApnPasswordText"),
    )
    for key, element in fields:
        if key in inputs:
            await set_value(page, element, inputs[key])
    if "auth" in inputs:
        await click(page, f"editApnAuth_{_AUTH_IDS[inputs['auth']]}")
    if "ip_type" in inputs:
        await click(page, f"editConType_{_IP_IDS[inputs['ip_type']]}")
    if "enabled" in inputs:
        await set_checked(page, "_EditApnStatusCheckBox", checked=inputs["enabled"])
    await click(page, "_EditApn_modal_btn")


async def delete_apn(page: BrowserPage, inputs: dict[str, Any]) -> None:
    await click(page, f"ApnDelBtn{await _apn_position(page, inputs['instance'])}")
    await click(page, "_dialog_modal_Btn")  # the confirmation dialog's button


def _scenario(
    name: str, endpoint: Endpoint, call: str, drive: Any, inputs: dict[str, Any], **kw: Any
) -> Scenario:
    return Scenario(
        name=name,
        page=Page.CELLULAR_SETTINGS,
        endpoint=endpoint,
        call=call,
        inputs=inputs,
        drive=drive,
        **kw,
    )


def _mode(name: str, mode: str) -> Scenario:
    return _scenario(
        name, Endpoint.CELLULAR_MODE, "cellular.set_network_mode", network_mode, {"mode": mode}
    )


def _default(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return _scenario(
        name, Endpoint.APN_DEFAULT_SAVE, "cellular.set_default_apn", default_apn, inputs, **kw
    )


def _add(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return _scenario(name, Endpoint.APN_ADD, "cellular.add_apn", add_apn, inputs, **kw)


def _edit(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return _scenario(name, Endpoint.APN_EDIT, "cellular.edit_apn", edit_apn, inputs, **kw)


def _delete(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return _scenario(name, Endpoint.APN_DELETE, "cellular.delete_apn", delete_apn, inputs, **kw)


SCENARIOS = [
    _mode("cellular_mode_lte", "4G"),
    _mode("cellular_mode_nr_sa", "5G SA"),
    _mode("cellular_mode_auto", "4G/5G(Auto)"),
    Scenario(
        name="cellular_roaming_disable",
        page=Page.CELLULAR_SETTINGS,
        endpoint=Endpoint.ROAMING,
        call="cellular.disable_roaming",
        inputs={},
        drive=roaming,
        notes="one click on the (checked) switch: the UI then sends the number 0",
    ),
    Scenario(
        name="cellular_roaming_enable",
        page=Page.CELLULAR_SETTINGS,
        endpoint=Endpoint.ROAMING,
        call="cellular.enable_roaming",
        inputs={},
        drive=lambda page, _: roaming(page, {"clicks": 2}),
        notes="switch off and on again: the UI sends the number 1 (unclicked it sends '1')",
    ),
    _scenario(
        "cellular_operation_bridge",
        Endpoint.OPERATION_MODE,
        "cellular.set_operation_mode",
        operation_mode,
        {"mode": "Bridge"},
        call_kwargs={"confirm": True},
    ),
    _scenario(
        "cellular_operation_routing",
        Endpoint.OPERATION_MODE,
        "cellular.set_operation_mode",
        operation_mode,
        {"mode": "Routing"},
        call_kwargs={"confirm": True},
    ),
    _scenario(
        "cellular_search_operators",
        Endpoint.SEARCH_OPERATORS,
        "cellular.search_operators",
        search,
        {},
        answers={"req_SearchOperators": {"scan_network": SCAN}},
        notes="scan_network format inferred from the UI parser (insert_operators_data)",
    ),
    _scenario(
        "cellular_search_operators_none",
        Endpoint.SEARCH_OPERATORS,
        "cellular.search_operators",
        search,
        {},
        answers={"req_SearchOperators": {"scan_network": "No Avaiable Networks"}},
    ),
    _scenario(
        "cellular_register_operator",
        Endpoint.REGISTER_OPERATOR,
        "cellular.register_operator",
        register,
        {"mcc": "222", "mnc": "10"},
        answers={"req_SearchOperators": {"scan_network": SCAN}},
        notes="scan, then register an Available network; scan answer format inferred",
    ),
    _scenario(
        "cellular_register_operator_3digit_mnc",
        Endpoint.REGISTER_OPERATOR,
        "cellular.register_operator",
        register,
        {"mcc": "310", "mnc": "410"},
        answers={"req_SearchOperators": {"scan_network": SCAN_3DIGIT}},
    ),
    _default(
        "cellular_default_apn_text",
        {
            "apn": "web.example.it",
            "profile_name": "Profilo Wéb & 1",
            "username": "user@x",
            "password": "p&ss%41",
        },
        notes="the UI decodeURIComponent()s text fields: %41 is sent as A",
    ),
    _default(
        "cellular_default_apn_auth",
        {"auth": "PAPCHAP", "ip_type": "ipv6", "username": "a", "password": "b"},
        notes="untouched text fields are sent decoded",
    ),
    _default("cellular_default_apn_unchanged", {}),
    _default("cellular_default_apn_refused_empty", {"apn": ""}, refused=True),
    _default("cellular_default_apn_refused_long", {"apn": "a" * 33}, refused=True),
    _default("cellular_default_apn_refused_invalid", {"apn": "web_x.it"}, refused=True),
    _default("cellular_default_apn_refused_empty_name", {"profile_name": ""}, refused=True),
    _default("cellular_default_apn_refused_long_name", {"profile_name": "n" * 33}, refused=True),
    _default(
        "cellular_default_apn_refused_bad_percent",
        {"password": "100%"},
        refused=True,
        notes="decodeURIComponent throws (URIError): the UI sends nothing",
    ),
    _add(
        "cellular_apn_add",
        {
            "apn": "internet.example",
            "profile_name": "Mio profilo è",
            "auth": "NONE",
            "ip_type": "ipv4",
        },
    ),
    _add(
        "cellular_apn_add_auth",
        {
            "apn": "web2",
            "profile_name": "",
            "username": "u@x",
            "password": "p&w%",
            "auth": "PAPCHAP",
            "ip_type": "ipv6",
            "enabled": False,
        },
        notes="add sends the raw text (no decodeURIComponent, unlike default / edit)",
    ),
    _add("cellular_apn_add_refused_duplicate", {"apn": "fwavoip.tim.it"}, refused=True),
    _add(
        "cellular_apn_add_refused_no_credentials",
        {"apn": "web3", "auth": "CHAP", "username": "u"},
        refused=True,
    ),
    _add("cellular_apn_add_refused_long", {"apn": "a" * 33}, refused=True),
    _add("cellular_apn_add_refused_invalid", {"apn": "bad-apn.it"}, refused=True),
    _add("cellular_apn_add_refused_empty", {"apn": ""}, refused=True),
    _add(
        "cellular_apn_add_refused_full",
        {"apn": "sixth"},
        refused=True,
        fixture=FIVE_APNS,
        synthetic=True,
    ),
    _edit(
        "cellular_apn_edit",
        {
            "instance": 2,
            "apn": "voip2.tim.it",
            "profile_name": "VoIP & più",
            "auth": "PAP",
            "username": "me",
            "password": "pa%ss",
            "ip_type": "ipv4",
            "enabled": False,
        },
    ),
    _edit("cellular_apn_edit_unchanged", {"instance": 2}),
    _edit(
        "cellular_apn_edit_decoded",
        {"instance": 3},
        fixture=FIVE_APNS,
        synthetic=True,
        notes="the dialog is pre-filled with decoded values, sent back decoded",
    ),
    _edit(
        "cellular_apn_edit_other_row",
        {"instance": 5, "ip_type": "ipv4v6", "enabled": False},
        fixture=FIVE_APNS,
        synthetic=True,
    ),
    _edit(
        "cellular_apn_edit_refused_duplicate", {"instance": 2, "apn": "fwanat.tim.it"}, refused=True
    ),
    _edit("cellular_apn_edit_refused_invalid", {"instance": 2, "apn": "a b"}, refused=True),
    _edit(
        "cellular_apn_edit_refused_empty_name", {"instance": 2, "profile_name": ""}, refused=True
    ),
    _edit("cellular_apn_edit_refused_empty_apn", {"instance": 2, "apn": ""}, refused=True),
    _edit(
        "cellular_apn_edit_refused_long_name",
        {"instance": 2, "profile_name": "n" * 33},
        refused=True,
    ),
    _edit(
        "cellular_apn_edit_refused_no_credentials",
        {"instance": 2, "auth": "CHAP"},
        refused=True,
    ),
    _delete("cellular_apn_delete", {"instance": 2}),
    _delete(
        "cellular_apn_delete_encoded",
        {"instance": 3},
        fixture=FIVE_APNS,
        synthetic=True,
        notes="delete sends the stored entry as-is (still URI-encoded)",
    ),
    _delete("cellular_apn_delete_last", {"instance": 8}, fixture=FIVE_APNS, synthetic=True),
]
