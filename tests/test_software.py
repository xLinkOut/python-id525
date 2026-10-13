from __future__ import annotations

import pytest

from id525 import Id525CommandError, Id525ResponseError
from id525.sections.software import ACS_MAX_POLLS, parse_software_page

from .conftest import ClientFactory, FakeRouter, load_fixture

INPROGRESS = {"result": "inprogress"}


def test_parse_software_page() -> None:
    info = parse_software_page(load_fixture("adm-sw.html"))
    assert info.version is None  # empty in this dump
    assert info.build_date is None  # only the " (IST)" suffix
    assert info.upgrade_status is None


async def test_get_info(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    await client.software.get_info()
    assert router.count("page:adm-sw") == 1


async def test_check_gives_up_like_the_ui(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers = {"acs_check_update": INPROGRESS, "acs_check_update_status": INPROGRESS}
    client = await make_client(read_only=False)
    with pytest.raises(Id525ResponseError, match="still in progress"):
        await client.software.check_for_update(poll_interval=0)
    assert router.count("acs_check_update_status") == ACS_MAX_POLLS


async def test_check_rejected(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers = {"acs_check_update": {"result": False, "error": "no ACS"}}
    client = await make_client(read_only=False)
    with pytest.raises(Id525CommandError, match="no ACS"):
        await client.software.check_for_update(poll_interval=0)


async def test_check_unexpected_answer(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers = {"acs_check_update": {"result": "busy"}}
    client = await make_client(read_only=False)
    with pytest.raises(Id525ResponseError, match="busy"):
        await client.software.check_for_update(poll_interval=0)
