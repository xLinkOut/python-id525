from __future__ import annotations

import pytest

from id525 import Id525CommandError, Id525ValidationError
from id525.sections.cellular import (
    ApnAuth,
    ApnIpType,
    NetworkMode,
    OperationMode,
    decode_uri_component,
    is_valid_apn,
    js_length,
    parse_cellular_page,
    parse_scan_result,
)

from .conftest import ClientFactory, FakeRouter, load_fixture

SCAN = "222,1,97,TIM,12,0;222,10,34,vodafone IT,8,0;222,88,18,WINDTRE,8,0;"


def test_parse_cellular_page() -> None:
    cell = parse_cellular_page(load_fixture("cellular-settings.html"))
    assert cell.network_mode == "4G/5G(Auto)"
    assert cell.available_modes == ("4G/5G(Auto)", "4G", "5G SA")
    assert cell.scan_mode == "Automatic"
    assert cell.bridge_mode is False
    assert cell.model == "IDU"
    assert cell.sim_state == "Inserted"
    assert cell.pin_enabled is False
    assert cell.pin_retries == 3
    assert cell.roaming is True
    assert [a.instance for a in cell.apns] == [1, 2]
    default = cell.default_apn
    assert default is not None
    assert default.is_default
    assert (default.apn, default.profile_name) == ("fwanat.tim.it", "profile1")
    assert default.ip_type is ApnIpType.IPV4V6
    assert default.auth == "NONE"
    assert default.enabled
    assert default.active
    assert cell.apns[1].active is False


def test_parse_synthetic_apns_are_decoded() -> None:
    cell = parse_cellular_page(load_fixture("synthetic/cellular-settings-5-apns.html"))
    assert [a.instance for a in cell.apns] == [1, 2, 3, 5, 8]
    ims = cell.apns[2]
    assert (ims.profile_name, ims.username, ims.password) == ("ims profile", "user@example", "p&ss")
    assert ims.ip_type is ApnIpType.IPV6
    assert ims.enabled is False


def test_scan_parser_mirrors_the_ui() -> None:
    ops = parse_scan_result(SCAN)
    assert [(o.mcc, o.mnc, o.state) for o in ops] == [
        ("222", "1", "Current Serving"),
        ("222", "10", "Available"),
        ("222", "88", "Forbidden"),
    ]
    # the UI drops the last ';'-separated element
    assert len(parse_scan_result("222,1,34,A,8,0;222,2,34,B,8,0")) == 1
    assert parse_scan_result("No Avaiable Networks") == ()
    assert parse_scan_result("") == ()


def test_js_helpers() -> None:
    assert decode_uri_component("a%20b%41") == "a bA"
    for bad in ("100%", "%zz", "%C3"):
        with pytest.raises(Id525ValidationError):
            decode_uri_component(bad)
    assert js_length("😀") == 2
    assert is_valid_apn("a.b.c.d")
    assert not is_valid_apn("a.b.c.d.e")
    assert not is_valid_apn("bad-apn")


async def test_get_settings(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    cell = await client.cellular.get_settings()
    assert cell.roaming
    assert router.count("page:cellular-settings") == 1


async def test_search_operators(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers["req_SearchOperators"] = {"scan_network": SCAN}
    client = await make_client(read_only=False)
    ops = await client.cellular.search_operators()
    assert [o.name for o in ops] == ["TIM", "vodafone IT", "WINDTRE"]


async def test_search_failure_raises(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers["req_SearchOperators"] = {"result": False, "error": "busy"}
    client = await make_client(read_only=False)
    with pytest.raises(Id525CommandError, match="busy"):
        await client.cellular.search_operators()


@pytest.mark.parametrize(
    ("mcc", "mnc", "message"),
    [
        ("222", "1", "Current Serving"),
        ("222", "88", "Forbidden"),
        ("999", "99", "not found"),
    ],
)
async def test_register_refuses_what_the_ui_does_not_offer(
    mcc: str, mnc: str, message: str, make_client: ClientFactory, router: FakeRouter
) -> None:
    router.answers["req_SearchOperators"] = {"scan_network": SCAN}
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match=message):
        await client.cellular.register_operator(mcc, mnc)
    assert "req_RegistingOperators" not in router.calls


async def test_register_accepts_the_padded_mnc(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    router.answers["req_SearchOperators"] = {"scan_network": "222,1,34,TIM,12,0;"}
    client = await make_client(read_only=False)
    await client.cellular.register_operator("222", "01")
    assert router.count("req_RegistingOperators") == 1


async def test_unknown_network_mode_is_rejected(make_client: ClientFactory) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(ValueError, match="5G NSA"):
        await client.cellular.set_network_mode("5G NSA")  # type: ignore[arg-type]
    await client.cellular.set_network_mode(NetworkMode.LTE)


async def test_operation_mode_forgets_the_session(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    router.drop.add("req_LanOperationModeSave")
    client = await make_client(read_only=False)
    await client.cellular.set_operation_mode(OperationMode.BRIDGE, confirm=True)
    assert router.count("req_LanOperationModeSave") == 1
    assert not client.is_logged_in


@pytest.mark.parametrize("instance", [1, 99])
async def test_edit_and_delete_only_user_apns(
    instance: int, make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError):
        await client.cellular.edit_apn(instance, apn="x")
    with pytest.raises(Id525ValidationError):
        await client.cellular.delete_apn(instance)
    assert not {"req_editUserApn", "req_deleteUserApn"} & set(router.calls)


async def test_enum_or_string_arguments(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client(read_only=False)
    await client.cellular.add_apn("web", auth=ApnAuth.NONE, ip_type=ApnIpType.IPV4)
    await client.cellular.add_apn("web2", auth="NONE", ip_type="ipv6")  # type: ignore[arg-type]
    assert router.count("req_addUserApn") == 2
