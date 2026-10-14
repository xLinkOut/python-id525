from __future__ import annotations

from datetime import date, timedelta

import pytest

from id525 import Id525ConfirmationRequiredError, Id525ValidationError
from id525.sections.account import DataUnit, parse_account_page

from .conftest import ClientFactory, FakeRouter, load_fixture


def test_parse_account_page() -> None:
    account = parse_account_page(load_fixture("adm-user.html"))
    assert account.username == "admin"
    assert account.session_timeout == timedelta(minutes=5)
    assert account.statistics_duration == timedelta(days=408, hours=15, minutes=45, seconds=8)
    assert account.statistics_reset_date == date(2025, 8, 20)
    assert account.total_data_gb == pytest.approx(4477.64)
    assert account.data_limit == 0
    assert account.data_limit_unit is None


async def test_get_settings(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    assert (await client.account.get_settings()).username == "admin"
    assert router.count("page:adm-user") == 1


async def test_password_change_switches_credentials(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(read_only=False)
    await client.account.change_password("old", "NewPass#2024", username="admin", confirm=True)
    assert router.count("set_account_management") == 1
    assert router.count("page:adm-user") == 0  # username given: no page read
    assert client._password == "NewPass#2024"
    assert not client.is_logged_in  # the UI goes back to the login page


async def test_password_change_needs_confirmation(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ConfirmationRequiredError):
        await client.account.change_password("old", "NewPass#2024")
    assert router.calls == []


@pytest.mark.parametrize("minutes", [0, 61, -5])
async def test_session_timeout_bounds(minutes: int, make_client: ClientFactory) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError):
        await client.account.set_session_timeout(minutes)


async def test_data_limit_accepts_unit_strings(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(read_only=False)
    await client.account.set_data_limit(10, "MB")  # type: ignore[arg-type]
    assert router.bodies[-1][1].endswith(b'"data_value":"10","data_unit":"MB"}')
    with pytest.raises(ValueError, match="TB"):
        await client.account.set_data_limit(10, "TB")  # type: ignore[arg-type]
    assert DataUnit("GB") is DataUnit.GB
