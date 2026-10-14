from __future__ import annotations

import pytest

from id525 import Id525CommandError, Id525ResponseError, Id525ValidationError
from id525.sections.wifi import (
    WifiBand,
    WifiBandwidth,
    WifiInterface,
    WifiMode,
    WifiSecurity,
    WpsResult,
    js_decode_uri_component,
    parse_wifi_page,
)

from .conftest import ClientFactory, FakeRouter, load_fixture

NO_MLO = "synthetic/wifi-settings-no-mlo"


def test_parse_wifi_page() -> None:
    wifi = parse_wifi_page(load_fixture("wifi-settings.html"))
    assert wifi.mlo_enabled is True
    assert wifi.mesh_controller is False
    assert wifi.wps_enabled is True
    radio_2g, radio_5g = wifi.radios
    assert (radio_2g.band, radio_2g.bandwidth, radio_2g.channel) == (WifiBand.GHZ_2_4, "20MHz", 0)
    assert (radio_5g.mode, radio_5g.bandwidth) == ("11bea", "160MHz")
    assert radio_5g.channels[:3] == (36, 40, 44)
    main = wifi.network(WifiInterface.MAIN_2G)
    assert main.ssid == "TestNet-24"  # URI-decoded from TestNet%2D24
    assert main.passphrase == "TestPass0002"
    assert main.security == WifiSecurity.WPA2
    assert (main.enabled, main.hidden, main.max_devices, main.instance) == (True, False, 64, 0)
    guest = wifi.network(WifiInterface.GUEST_5G)
    assert (guest.enabled, guest.max_devices, guest.instance) == (False, 32, 3)


def test_interface_properties() -> None:
    assert WifiInterface.GUEST_2G.band is WifiBand.GHZ_2_4
    assert WifiInterface.MAIN_5G.is_main
    assert not WifiInterface.GUEST_5G.is_main


@pytest.mark.parametrize(
    ("value", "decoded"),
    [("TestNet%2D24", "TestNet-24"), ("plain", "plain"), ("%C3%A8", "è"), ("a+b", "a+b")],
)
def test_js_decode_uri_component(value: str, decoded: str) -> None:
    assert js_decode_uri_component(value) == decoded


@pytest.mark.parametrize("value", ["50%", "%zz", "%C3"])
def test_js_decode_uri_component_throws_like_js(value: str) -> None:
    with pytest.raises(ValueError, match="escape"):
        js_decode_uri_component(value)


async def test_get_settings(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    wifi = await client.wifi.get_settings()
    assert len(wifi.networks) == 4
    assert router.count("page:wifi-settings") == 1


@pytest.mark.parametrize(
    ("call", "kwargs", "message"),
    [
        ("update_network", {"interface": "5G_Main", "ssid": "50% off"}, "URI-decodes"),
        ("update_network", {"interface": "5G_Main", "passphrase": "Ab1%Ab1%Ab"}, "URI-decodes"),
        ("update_radio", {"band": "2.4G", "bandwidth": "80MHz"}, "not offered"),
        ("update_radio", {"band": "5G", "channel": 1}, "not offered"),
        ("update_radio", {"band": "5G", "mode": "11ng"}, "not a 5G mode"),
    ],
)
async def test_refused_before_sending(
    call: str,
    kwargs: dict[str, object],
    message: str,
    make_client: ClientFactory,
    router: FakeRouter,
) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match=message):
        await getattr(client.wifi, call)(**kwargs)
    assert "req_wifiSetting" not in router.calls


async def test_guest_networks_are_hidden_in_mesh_mode(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    router.page_fixtures["wifi-settings"] = "synthetic/wifi-settings-mesh"
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match="mesh"):
        await client.wifi.update_network(WifiInterface.GUEST_2G, ssid="x")
    assert router.calls.count("req_wpsSetting") == 0


async def test_mesh_save_stops_if_wps_is_refused(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    router.page_fixtures["wifi-settings"] = "synthetic/wifi-settings-mesh"
    router.answers["req_wpsSetting"] = {"result": False}
    client = await make_client(read_only=False)
    with pytest.raises(Id525CommandError, match="req_wpsSetting"):
        await client.wifi.update_network(WifiInterface.MAIN_5G, ssid="x")
    assert "req_wifiSetting" not in router.calls


async def test_5g_channel_width_couplings(make_client: ClientFactory, router: FakeRouter) -> None:
    router.page_fixtures["wifi-settings"] = NO_MLO
    client = await make_client(read_only=False)
    await client.wifi.update_radio(
        WifiBand.GHZ_5, mode=WifiMode.N_A, bandwidth=WifiBandwidth.MHZ_80, channel=0
    )
    sent = [b for n, b in router.bodies if n == "req_wifiSetting"][-1]
    assert b'"Bandwidth5G":2,"WiFiMode5G":"11bea","Channel5G":0' in sent


async def test_wps_unknown_status(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers["req_wpsCheckScan"] = {"wpsStatus": 9}
    client = await make_client(read_only=False)
    with pytest.raises(Id525ResponseError, match="unknown WPS status"):
        await client.wifi.start_wps(poll_interval=0)


async def test_wps_failed_poll(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers["req_wpsCheckScan"] = [{"wpsStatus": 0}, {"result": False}]
    client = await make_client(read_only=False)
    assert await client.wifi.start_wps(poll_interval=0) is WpsResult.FAILED
    assert router.calls.count("req_wpsCheckScan") == 2
