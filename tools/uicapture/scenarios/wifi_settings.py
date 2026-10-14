"""wifi-settings.html: networks, radios, MLO and WPS."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from id525.endpoints import Endpoint, Page
from id525.sections.wifi import WifiBand, WifiInterface

from .base import Scenario, click, platform_prefix, set_value

if TYPE_CHECKING:
    from playwright.async_api import Page as BrowserPage

_SECURITY_ITEM = {
    "OPEN": "NONE",
    "WPA-PSK/WPA2-PSK": "WPA12",
    "WPA2-PSK": "WPA2",
    "WPA2-PSK/WPA3-PSK": "WPA23",
    "WPA3-PSK": "WPA3",
}
_MODE_ITEM = {
    "11beg": "wifiMode_be_ax_bgn",
    "11axg": "wifiMode_ax_bgn",
    "11ng": "wifiMode_bgn",
    "11bg": "wifiMode_bg",
    "11bea": "wifiMode_be_ax_ac_na",
    "11axa": "wifiMode_ax_ac_na",
    "11ac": "wifiMode_ac_na",
    "11na": "wifiMode_na",
}
_BANDWIDTH_ITEM = {
    "Auto(20/40MHz)": "wifiBandwidth_Auto",
    "20MHz": "wifiBandwidth_20",
    "40MHz": "wifiBandwidth_40",
    "80MHz": "wifiBandwidth_80",
    "160MHz": "wifiBandwidth_160",
}


async def set_checked(page: BrowserPage, element_id: str, checked: bool) -> None:  # noqa: FBT001
    """Flip a switch like a user (fires the change handler)."""
    await page.evaluate(
        """([id, checked]) => {
            const el = document.getElementById(id);
            if (!el) throw new Error("no element #" + id);
            el.checked = checked;
            el.dispatchEvent(new Event("change", {bubbles: true}));
        }""",
        [element_id, checked],
    )


async def ui_error(page: BrowserPage) -> bool:
    """Return True if the UI is showing an error (the user would stop there)."""
    text: str = await page.evaluate(
        "() => (document.getElementById('_dialog_modal_warning') || {}).textContent || ''"
    )
    return bool(text.strip())


def _band_id(band: WifiBand) -> str:
    return "24" if band is WifiBand.GHZ_2_4 else "5"


async def update_network(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    iface = WifiInterface(inputs["interface"])
    await click(page, f"{pf}-RadioSelect_{_band_id(iface.band)}")
    kind = "Main" if iface.is_main else "Guest"
    await click(page, f"wifiInterface_{_band_id(iface.band)}_{kind}")
    if "enabled" in inputs:
        await set_checked(page, f"{pf}-wifiRadioCheckbox", inputs["enabled"])
    if "ssid" in inputs:
        await set_value(page, f"{pf}-wifiSSIDText", inputs["ssid"])
    if "security" in inputs:
        await click(page, f"{pf}-SecuritySelect_{_SECURITY_ITEM[inputs['security']]}")
    if "passphrase" in inputs:
        await set_value(page, f"{pf}-wifiPasswordText", inputs["passphrase"])
    if "max_devices" in inputs:
        await set_value(page, f"{pf}-wifiMaxNumberText", str(inputs["max_devices"]))
    if "hidden" in inputs:
        await set_checked(page, f"{pf}-ssidHiddenCheckbox", inputs["hidden"])
    await click(page, f"{pf}-wifiSetting_BT")


async def update_radio(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    await click(page, f"{pf}-RadioSelect_{_band_id(WifiBand(inputs['band']))}")
    if "mode" in inputs:
        await click(page, _MODE_ITEM[inputs["mode"]])
        if await ui_error(page):
            return
    if "bandwidth" in inputs:
        await click(page, _BANDWIDTH_ITEM[inputs["bandwidth"]])
    if "channel" in inputs:
        await click(page, f"wifiChannel{inputs['channel']}")
    await click(page, f"{pf}-wifiSetting_BT")


async def set_mlo(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    await set_checked(page, f"{pf}-wifiMloCheckbox", inputs["enabled"])
    await click(page, f"{pf}-wifiSetting_BT")


async def set_wps(page: BrowserPage, inputs: dict[str, Any]) -> None:
    pf = await platform_prefix(page)
    await set_checked(page, f"{pf}-WPSStatusCheckBox", inputs["enabled"])
    await click(page, f"{pf}-WPSSaveBtn")


async def start_wps(page: BrowserPage, inputs: dict[str, Any]) -> None:
    del inputs
    await click(page, f"{await platform_prefix(page)}-WPSScanBtn")


async def stop_wps(page: BrowserPage, inputs: dict[str, Any]) -> None:
    """Click the scan button while it reads "Stop" (a session is running)."""
    del inputs
    pf = await platform_prefix(page)
    await page.evaluate(
        "(id) => { document.getElementById(id).innerHTML = i18next.t('wifi_wps_stop'); }",
        f"{pf}-WPSScanBtn",
    )
    await click(page, f"{pf}-WPSScanBtn")


def _network(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.WIFI_SETTINGS,
        endpoint=Endpoint.WIFI_SETTING,
        call="wifi.update_network",
        inputs=inputs,
        drive=update_network,
        **kw,
    )


def _radio(name: str, inputs: dict[str, Any], **kw: Any) -> Scenario:
    return Scenario(
        name=name,
        page=Page.WIFI_SETTINGS,
        endpoint=Endpoint.WIFI_SETTING,
        call="wifi.update_radio",
        inputs=inputs,
        drive=update_radio,
        **kw,
    )


_NO_MLO: dict[str, Any] = {"fixture": "synthetic/wifi-settings-no-mlo", "synthetic": True}
_WPS_DONE = {"req_wpsCheckScan": [{"wpsStatus": 0}, {"wpsStatus": 0}, {"wpsStatus": 1}]}

SCENARIOS = [
    _network(
        "wifi_main_5g_ssid_passphrase",
        {"interface": "5G_Main", "ssid": "Casa Rossi è 5G", "passphrase": "Pass word_1(x)"},
        notes="MLO is on: the 2.4 GHz main network takes the same SSID and passphrase",
    ),
    _network(
        "wifi_guest_2g_full",
        {
            "interface": "2.4G_Guest",
            "enabled": True,
            "ssid": "Ospiti & \"amici\" 'ü'",
            "security": "WPA2-PSK/WPA3-PSK",
            "passphrase": "Guest!Pass99",
            "max_devices": 8,
            "hidden": True,
        },
    ),
    _network(
        "wifi_main_2g_disable_open",
        {"interface": "2.4G_Main", "enabled": False, "security": "OPEN"},
        notes="disabling skips the passphrase checks of that network; MLO mirrors security",
    ),
    _network(
        "wifi_guest_5g_max_devices_clamped",
        {"interface": "5G_Guest", "enabled": True, "max_devices": 70},
        notes="the UI's input box clamps values above 64",
    ),
    _network("wifi_refused_empty_ssid", {"interface": "5G_Main", "ssid": ""}, refused=True),
    _network("wifi_refused_long_ssid", {"interface": "5G_Main", "ssid": "s" * 33}, refused=True),
    _network(
        "wifi_refused_short_passphrase",
        {"interface": "5G_Main", "passphrase": "Ab1!xyz"},
        refused=True,
    ),
    _network(
        "wifi_refused_passphrase_symbol",
        {"interface": "5G_Main", "passphrase": "Password1&x"},
        refused=True,
    ),
    _network(
        "wifi_refused_weak_passphrase",
        {"interface": "2.4G_Guest", "enabled": True, "passphrase": "abcdefghijk"},
        refused=True,
    ),
    _network(
        "wifi_refused_max_devices",
        {"interface": "5G_Main", "max_devices": 1},
        refused=True,
    ),
    _network(
        "wifi_no_mlo_main_2g_ssid",
        {"interface": "2.4G_Main", "ssid": "Solo 2.4"},
        notes="without MLO the 2.4 GHz main network is independent",
        **_NO_MLO,
    ),
    _network(
        "wifi_mesh_main_5g_ssid",
        {"interface": "5G_Main", "ssid": "Mesh net"},
        fixture="synthetic/wifi-settings-mesh",
        synthetic=True,
        notes="mesh controller with WPS off: the UI re-sends the WPS flag before saving",
    ),
    _radio(
        "wifi_radio_5g_width_channel",
        {"band": "5G", "bandwidth": "40MHz", "channel": 36},
    ),
    _radio(
        "wifi_radio_2g_width_channel",
        {"band": "2.4G", "bandwidth": "Auto(20/40MHz)", "channel": 6},
    ),
    _radio(
        "wifi_radio_refused_mode_with_mlo",
        {"band": "5G", "mode": "11axa"},
        refused=True,
        notes="with MLO only the 802.11be modes are allowed",
    ),
    _radio(
        "wifi_no_mlo_radio_5g_mode_na",
        {"band": "5G", "mode": "11na", "channel": 100},
        notes="802.11n/a forces 40 MHz",
        **_NO_MLO,
    ),
    _radio(
        "wifi_no_mlo_radio_2g_mode_bg_then_auto",
        {"band": "2.4G", "mode": "11bg", "bandwidth": "Auto(20/40MHz)"},
        notes="802.11g/b forces 20 MHz, then Auto width restores be/ax/n/g/b",
        **_NO_MLO,
    ),
    Scenario(
        name="wifi_mlo_disable",
        page=Page.WIFI_SETTINGS,
        endpoint=Endpoint.WIFI_SETTING,
        call="wifi.set_mlo",
        inputs={"enabled": False},
        drive=set_mlo,
    ),
    Scenario(
        name="wifi_mlo_enable",
        page=Page.WIFI_SETTINGS,
        endpoint=Endpoint.WIFI_SETTING,
        call="wifi.set_mlo",
        inputs={"enabled": True},
        drive=set_mlo,
        notes="enabling copies the 5 GHz main network and forces the be modes",
        **_NO_MLO,
    ),
    Scenario(
        name="wifi_wps_disable",
        page=Page.WIFI_SETTINGS,
        endpoint=Endpoint.WPS_SETTING,
        call="wifi.set_wps",
        inputs={"enabled": False},
        drive=set_wps,
    ),
    Scenario(
        name="wifi_wps_enable",
        page=Page.WIFI_SETTINGS,
        endpoint=Endpoint.WPS_SETTING,
        call="wifi.set_wps",
        inputs={"enabled": True},
        drive=set_wps,
        fixture="synthetic/wifi-settings-wps-off",
        synthetic=True,
    ),
    Scenario(
        name="wifi_wps_start_success",
        page=Page.WIFI_SETTINGS,
        endpoint=Endpoint.WPS_START,
        call="wifi.start_wps",
        inputs={},
        call_kwargs={"poll_interval": 0},
        answers=_WPS_DONE,
        drive=start_wps,
        notes="the UI polls req_wpsCheckScan every second while wpsStatus is 0",
    ),
    Scenario(
        name="wifi_wps_start_timeout",
        page=Page.WIFI_SETTINGS,
        endpoint=Endpoint.WPS_START,
        call="wifi.start_wps",
        inputs={},
        call_kwargs={"poll_interval": 0},
        answers={"req_wpsCheckScan": {"wpsStatus": 3}},
        drive=start_wps,
    ),
    Scenario(
        name="wifi_wps_start_rejected",
        page=Page.WIFI_SETTINGS,
        endpoint=Endpoint.WPS_START,
        call="wifi.start_wps",
        inputs={},
        call_kwargs={"poll_interval": 0},
        answers={"req_wpsStartScan": {"result": False}},
        drive=start_wps,
        notes="a refused start ends the session without polling",
    ),
    Scenario(
        name="wifi_wps_start_refused_disabled",
        page=Page.WIFI_SETTINGS,
        endpoint=Endpoint.WPS_START,
        call="wifi.start_wps",
        inputs={},
        drive=start_wps,
        refused=True,
        fixture="synthetic/wifi-settings-wps-off",
        synthetic=True,
        notes="the scan button is disabled while WPS is off",
    ),
    Scenario(
        name="wifi_wps_start_refused_wpa3",
        page=Page.WIFI_SETTINGS,
        endpoint=Endpoint.WPS_START,
        call="wifi.start_wps",
        inputs={},
        drive=start_wps,
        refused=True,
        fixture="synthetic/wifi-settings-wpa3",
        synthetic=True,
    ),
    Scenario(
        name="wifi_wps_stop",
        page=Page.WIFI_SETTINGS,
        endpoint=Endpoint.WPS_STOP,
        call="wifi.stop_wps",
        inputs={},
        drive=stop_wps,
    ),
]
