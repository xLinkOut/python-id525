"""adm-user.html: admin password, session timeout, data usage."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page

from .base import Scenario, click, platform_prefix, set_value

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage


async def change_password(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    if "username" in inputs:
        await set_value(page, f"{pf}-new_username", inputs["username"])
    await set_value(page, f"{pf}-currentPWD", inputs["current_password"])
    await set_value(page, f"{pf}-newPWD", inputs["new_password"])
    await set_value(page, f"{pf}-confirmPWD", inputs["new_password"])
    await click(page, f"{pf}-update_user_pwd_btn")


async def session_timeout(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    await set_value(page, f"{pf}-input_session_timeout", str(inputs["minutes"]))
    await click(page, f"{pf}-device_management_save_btn")


async def reset_data(page: BrowserPage, inputs: dict[str, Any]) -> None:
    del inputs
    await click(page, f"{await platform_prefix(page)}-resetBtn")


async def data_limit(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    await set_value(page, f"{pf}-data_num", str(inputs["value"]))
    await click(page, f"{pf}-data_unit_{inputs['unit'].lower()}")
    await click(page, f"{pf}-data_usage_save_btn")


def _password(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.ACCOUNT,
        endpoint=Endpoint.SET_ACCOUNT,
        call="account.change_password",
        inputs=inputs,
        call_kwargs={"confirm": True},
        drive=change_password,
        **kw,
    )


def _timeout(name: str, minutes: int, **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.ACCOUNT,
        endpoint=Endpoint.SET_DEVICE_MANAGEMENT,
        call="account.set_session_timeout",
        inputs={"minutes": minutes},
        drive=session_timeout,
        **kw,
    )


def _limit(name: str, value: int, unit: str, **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.ACCOUNT,
        endpoint=Endpoint.DATA_USAGE_SAVE,
        call="account.set_data_limit",
        inputs={"value": value, "unit": unit},
        drive=data_limit,
        **kw,
    )


_OLD = "Old Pass 1!"

SCENARIOS = [
    _password(
        "account_password",
        {"current_password": _OLD, "new_password": "NewPass#2024"},
        notes="username omitted: the page's current one is sent",
    ),
    _password(
        "account_password_and_username",
        {"current_password": "p@ss w0rd", "new_password": "Zz 9.~{zz}", "username": "operator 1"},
        notes="spaces, ~ and braces are allowed: none of the UI's checks covers them",
    ),
    _password(
        "account_password_refused_short",
        {"current_password": _OLD, "new_password": "Ab1!"},
        refused=True,
    ),
    _password(
        "account_password_refused_long",
        {"current_password": _OLD, "new_password": "Ab1!" * 8 + "x"},
        refused=True,
    ),
    _password(
        "account_password_refused_not_allowed_char",
        {"current_password": _OLD, "new_password": "Pass&word1!"},
        refused=True,
    ),
    _password(
        "account_password_refused_non_ascii",
        {"current_password": _OLD, "new_password": "Pässword1!"},
        refused=True,
    ),
    _password(
        "account_password_refused_forbidden_symbol",
        {"current_password": _OLD, "new_password": "Pass/word1!"},
        refused=True,
    ),
    _password(
        "account_password_refused_no_letter",
        {"current_password": _OLD, "new_password": "12345678!"},
        refused=True,
    ),
    _password(
        "account_password_refused_no_digit",
        {"current_password": _OLD, "new_password": "Password!"},
        refused=True,
    ),
    _password(
        "account_password_refused_no_symbol",
        {"current_password": _OLD, "new_password": "Password1"},
        refused=True,
    ),
    _password(
        "account_password_refused_bad_username",
        {"current_password": _OLD, "new_password": "NewPass#2024", "username": "ad,min"},
        refused=True,
    ),
    _timeout("account_session_timeout_min", 1),
    _timeout("account_session_timeout_max", 60),
    _timeout("account_session_timeout_refused_zero", 0, refused=True),
    _timeout("account_session_timeout_refused_61", 61, refused=True),
    Scenario(
        name="account_reset_data_usage",
        page=Page.ACCOUNT,
        endpoint=Endpoint.RESET_DATA,
        call="account.reset_data_usage",
        inputs={},
        call_kwargs={"confirm": True},
        drive=reset_data,
        notes="no input: one scenario covers it; the UI asks no confirmation",
    ),
    _limit("account_data_limit_gb", 500, "GB"),
    _limit("account_data_limit_mb", 1, "MB"),
    _limit("account_data_limit_refused_zero", 0, "GB", refused=True),
    _limit("account_data_limit_refused_1000", 1000, "MB", refused=True),
]
