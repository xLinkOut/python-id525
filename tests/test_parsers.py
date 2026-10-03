from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from id525 import ClientInterface, Id525ResponseError, LoginState, SimState
from id525.parsers import (
    clean_str,
    extract_entity_json,
    is_redirect_page,
    parse_about_page,
    parse_cellular_page,
    parse_clients,
    parse_data_gb,
    parse_duration,
    parse_int,
    parse_network_status,
    parse_number,
    parse_rate_bps,
    parse_reset_date,
    parse_sms,
    parse_sms_time,
    parse_unit_duration,
    parse_utilization_page,
    split_list,
    uri_decode,
)

from .conftest import REDIRECT_PAGE, load_fixture


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("-79.0dBm", -79.0),
        ("20.0dB", 20.0),
        ("80.0MHz", 80.0),
        (163, 163.0),
        ("", None),
        (None, None),
        ("n/a", None),
        (True, None),
    ],
)
def test_parse_number(value: object, expected: float | None) -> None:
    assert parse_number(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"), [("163", 163), ("4", 4), ("1.5", None), ("x", None), (None, None)]
)
def test_parse_int(value: object, expected: int | None) -> None:
    assert parse_int(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("37,10:55:44", timedelta(days=37, hours=10, minutes=55, seconds=44)),
        ("0,00:00:05", timedelta(seconds=5)),
        ("garbage", None),
        (None, None),
    ],
)
def test_parse_duration(value: object, expected: timedelta | None) -> None:
    assert parse_duration(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("47 day(s), 01 Hr, 33 Min, 13 Sec.", timedelta(days=47, hours=1, minutes=33, seconds=13)),
        ("30 second(s)", timedelta(seconds=30)),
        ("5 Min", timedelta(minutes=5)),
        ("", None),
    ],
)
def test_parse_unit_duration(value: str, expected: timedelta | None) -> None:
    assert parse_unit_duration(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("300.77 GB", 300.77),
        ("512 MB", 0.5),
        ("1 TB", 1024.0),
        ("2", 2.0),
        ("1 PB", None),
        ("", None),
    ],
)
def test_parse_data_gb(value: str, expected: float | None) -> None:
    assert parse_data_gb(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("17 Kbps", 17_000.0),
        ("436.89 Mbps", 436_890_000.0),
        ("48 bps", 48.0),
        ("1.2 Gbps", 1.2e9),
        ("12", None),
        ("", None),
    ],
)
def test_parse_rate_bps(value: str, expected: float | None) -> None:
    result = parse_rate_bps(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_parse_reset_date() -> None:
    assert parse_reset_date("2025-08-20") == date(2025, 8, 20)
    assert parse_reset_date("1980-01-06") is None  # router's "never reset"
    assert parse_reset_date("bad") is None
    assert parse_reset_date("") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026/10/01 08:15:00", datetime(2026, 10, 1, 8, 15)),  # noqa: DTZ001
        ("2026-10-01T08:15:00", datetime(2026, 10, 1, 8, 15)),  # noqa: DTZ001
        ("26/10/01,08:15:00", datetime(2026, 10, 1, 8, 15)),  # noqa: DTZ001
        ("whenever", None),
        ("", None),
    ],
)
def test_parse_sms_time(value: str, expected: datetime | None) -> None:
    assert parse_sms_time(value) == expected


def test_misc_helpers() -> None:
    assert split_list("1.1.1.1, 8.8.8.8 9.9.9.9") == ("1.1.1.1", "8.8.8.8", "9.9.9.9")
    assert split_list("") == ()
    assert uri_decode("My%5FNet%2D5G") == "My_Net-5G"
    assert uri_decode("") is None
    assert clean_str("  N/A ") is None
    assert clean_str(" x ") == "x"


def test_enums_are_lenient() -> None:
    assert SimState("Connected (Roaming)") is SimState.CONNECTED_ROAMING
    assert SimState("Invalid SIM (blocked)") is SimState.INVALID_SIM
    assert SimState("something new") is SimState.UNKNOWN
    assert ClientInterface("USB") is ClientInterface.UNKNOWN
    assert LoginState(42) is LoginState.UNKNOWN


def test_is_redirect_page() -> None:
    assert is_redirect_page(REDIRECT_PAGE)
    assert not is_redirect_page(load_fixture("cellular-status.html"))


def test_extract_entity_json_errors() -> None:
    with pytest.raises(Id525ResponseError, match="not found"):
        extract_entity_json("<html></html>", "cellInfo")
    with pytest.raises(Id525ResponseError, match="not valid JSON"):
        extract_entity_json("var cellInfo = '{ broken';\n", "cellInfo")


def test_net_info_embedded_in_page_matches_endpoint_schema() -> None:
    page_data = extract_entity_json(load_fixture("net-status.html"), "net_info")
    api_data = json.loads(load_fixture("net_status.json"))
    assert set(api_data) - {"RequestVerifyToken"} == set(page_data)


def test_parse_network_status_fixture() -> None:
    status = parse_network_status(json.loads(load_fixture("net_status.json")))
    assert status.sim_state is SimState.CONNECTED
    assert status.is_connected
    assert not status.is_roaming
    assert status.signal_level == 4
    assert status.operation_mode == "5G I TIM"
    assert status.plmn == "22201"
    assert status.connection_duration == timedelta(days=37, hours=10, minutes=55, seconds=44)
    assert status.data_sent_gb == pytest.approx(300.77)
    assert status.data_received_gb == pytest.approx(4177.10)
    assert status.statistics_reset_date == date(2025, 8, 20)
    assert status.ipv4.address == "192.168.1.10"
    assert status.ipv4.netmask == "255.255.255.240"
    assert status.ipv4.dns == ("203.0.113.12",)
    assert status.ipv6.address is None
    assert status.ipv6.dns == ()
    assert status.lan_ip == "192.168.1.13"
    assert status.wifi_enabled is True
    assert status.ssid_2g == "TestNet-24"
    assert (status.wifi_clients_2g, status.wifi_clients_5g, status.usb_clients) == (2, 2, 0)
    assert status.ethernet_link_speeds == (1000, 1000)
    assert status.fqdn == "router.example"
    assert status.raw["plmn"] == "22201"


def test_parse_network_status_degraded() -> None:
    status = parse_network_status(
        {"sim_card_state": "No SIM", "signalLevel": "", "data_tx": "", "speed_eth1": "Down"}
    )
    assert status.sim_state is SimState.NO_SIM
    assert not status.is_connected
    assert status.signal_level is None
    assert status.data_sent_gb is None
    assert status.ethernet_link_speeds == (None,)
    assert status.wifi_enabled is False


def test_parse_clients_fixture() -> None:
    clients = parse_clients(json.loads(load_fixture("client_status.json")))
    assert len(clients) == 6
    first = clients[0]
    assert first.mac == "02:00:5e:00:00:01"
    assert first.hostname == "host-01"
    assert first.interface is ClientInterface.ETHERNET
    assert {c.interface for c in clients} == {
        ClientInterface.ETHERNET,
        ClientInterface.WIFI_2G,
        ClientInterface.WIFI_5G,
    }
    assert clients[4].hostname is None  # "N/A"
    assert parse_clients({}) == ()


def test_parse_cellular_page_fixture() -> None:
    info = parse_cellular_page(load_fixture("cellular-status.html"))
    assert len(info.cells) == 2
    nr = info.primary_5g
    lte = info.primary_4g
    assert nr is not None
    assert lte is not None
    assert nr.band == "n78"
    assert nr.bandwidth_mhz == 80.0
    assert nr.rsrp == -79.0
    assert nr.rsrq == -11.0
    assert nr.snr == 20.0
    assert nr.pci == 101
    assert nr.arfcn == 600001
    assert nr.cell_id == 12345671
    assert lte.band == "B3"
    assert lte.is_primary


def test_parse_utilization_page_fixture() -> None:
    util = parse_utilization_page(load_fixture("util-status.html"))
    assert util.cpu_percent.current == pytest.approx(30.6)
    assert util.cpu_percent.maximum == 100.0
    assert util.memory_percent.minimum == pytest.approx(71.99)
    assert util.uplink_bps.current == 17_000
    assert util.downlink_bps.maximum == pytest.approx(436.89e6)
    assert util.monitoring_window == timedelta(seconds=30)
    assert util.uptime == timedelta(days=47, hours=1, minutes=33, seconds=13)


def test_parse_utilization_page_missing() -> None:
    with pytest.raises(Id525ResponseError):
        parse_utilization_page("<html></html>")


def test_parse_about_page_fixture() -> None:
    about = parse_about_page(load_fixture("help-about.html"))
    assert about.model == "ID525"
    assert about.software_version == "ID525_REL_1.0.09.17"
    assert about.hardware_version == "3.0"
    assert about.imei == "350000000000000"
    assert about.imsi == "222010000000000"
    assert about.serial_number == "%SN0000000000"
    assert about.apns == ("fwanat.tim.it", "fwavoip.tim.it")
    assert about.mac == "02:00:5e:00:00:07"


def test_parse_about_page_missing() -> None:
    with pytest.raises(Id525ResponseError):
        parse_about_page("<html></html>")


def test_parse_sms_fixture() -> None:
    inbox = parse_sms(json.loads(load_fixture("sms_reload.json")))
    assert len(inbox.messages) == 3
    assert inbox.unread_count == 1
    assert len(inbox.inbound) == 2
    latest = inbox.latest
    assert latest is not None
    assert latest.index == 3  # newest *inbound*; the outbound one is newer
    assert latest.is_unread
    assert inbox.messages[2].is_outbound
    assert inbox.update_marker == "1759480000"


def test_parse_sms_empty() -> None:
    inbox = parse_sms({"result": True, "message": [], "sms_update_time": ""})
    assert inbox.unread_count == 0
    assert inbox.latest is None
