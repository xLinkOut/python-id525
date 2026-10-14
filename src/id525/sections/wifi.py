"""Wi-Fi radios, networks (SSIDs), MLO and WPS (``wifi-settings`` page).

The page keeps the whole Wi-Fi configuration in four JS lists (main / guest
network per band). Every edit in the UI mutates those lists, and "Save" posts
all of them at once (``req_wifiSetting``). The client replays exactly that:
:class:`_UiState` mirrors the page's JS state, each public method applies the
same handlers a user would trigger, in a fixed order, then builds the body the
UI's ``wifiSettingSave`` would send, after running the same validation chain.

Notable UI behaviours mirrored here:

* With MLO (or mesh controller) enabled the 2.4 GHz main network always takes
  SSID, security, cipher and passphrase of the 5 GHz main network.
* SSIDs and passphrases are URI-encoded in the page and URI-*decoded* by the
  UI on load, on input and again on save, so a literal ``%`` cannot be set
  through the UI: the client refuses it.
* Fields the user did not touch keep their JSON types from the page (some
  flags are strings such as ``"0"``); touched ones become numbers.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from ..const import TOKEN_FIELD
from ..endpoints import Endpoint, Page, uses
from ..exceptions import Id525CommandError, Id525ResponseError
from ..models import _raw
from ..parsers import extract_js_values
from .base import Section, invalid

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_SSID_LENGTH = 32
MIN_PASSPHRASE_LENGTH = 10
MAX_PASSPHRASE_LENGTH = 63
MIN_MAX_DEVICES = 2
MAX_MAX_DEVICES = 64
MAX_WPS_POLLS = 600

_WIFI_LIST_RE = re.compile(r"^\s*var (wifi_ssid_infos_(?:2|5)(?:_guest)?) = \"(.*?)\";", re.M)
_NUMERIC_VAR_RE = re.compile(r"^\s*var\s+(\w+)\s*=\s*(-?\d+)\s*;", re.M)
_ARRAY_VAR_RE = re.compile(r"^\s*var\s+(channel2G|channel5G)\s*=\s*\[([\d,\s]*)\]\s*;", re.M)
_PASSPHRASE_FORBIDDEN_RE = re.compile(r"['\"`%&+;:,<>?]")  # wifiPasswordCheck
_PASSPHRASE_SYMBOL_RE = re.compile(r"[!@#$^*()\[\]=_\-./\\|]")
_MALFORMED_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")


class WifiBand(StrEnum):
    """Radio band (``curRadio``)."""

    GHZ_2_4 = "2.4G"
    GHZ_5 = "5G"


class WifiInterface(StrEnum):
    """A network (SSID) of the router (``curInterface2G`` / ``curInterface5G``)."""

    MAIN_2G = "2.4G_Main"
    GUEST_2G = "2.4G_Guest"
    MAIN_5G = "5G_Main"
    GUEST_5G = "5G_Guest"

    @property
    def band(self) -> WifiBand:
        """Return the band of the network."""
        return WifiBand.GHZ_2_4 if self.value.startswith("2.4") else WifiBand.GHZ_5

    @property
    def is_main(self) -> bool:
        """Return True for the main (non-guest) network of a band."""
        return self.value.endswith("Main")


class WifiSecurity(StrEnum):
    """``Security_Mode`` values the UI can set."""

    OPEN = "OPEN"
    WPA_WPA2 = "WPA-PSK/WPA2-PSK"
    WPA2 = "WPA2-PSK"
    WPA2_WPA3 = "WPA2-PSK/WPA3-PSK"
    WPA3 = "WPA3-PSK"


class WifiMode(StrEnum):
    """802.11 mode (``WiFiMode2G`` / ``WiFiMode5G``)."""

    BE_AX_N_G_B = "11beg"
    AX_N_G_B = "11axg"
    N_G_B = "11ng"
    G_B = "11bg"
    BE_AX_AC_N_A = "11bea"
    AX_AC_N_A = "11axa"
    AC_N_A = "11ac"
    N_A = "11na"


class WifiBandwidth(StrEnum):
    """Channel width, as the UI names it (``curBandwidth2G`` / ``curBandwidth5G``)."""

    AUTO = "Auto(20/40MHz)"
    """2.4 GHz only."""
    MHZ_20 = "20MHz"
    MHZ_40 = "40MHz"
    """5 GHz only."""
    MHZ_80 = "80MHz"
    """5 GHz only."""
    MHZ_160 = "160MHz"
    """5 GHz only (shown as ``Auto(160/80/40/20MHz)``)."""


class WpsResult(IntEnum):
    """Outcome of a WPS pairing session (``wpsStatus`` of ``req_wpsCheckScan``)."""

    SUCCESS = 1
    FAILED = 2
    TIMEOUT = 3


_INTERFACE_LIST = {
    WifiInterface.MAIN_2G: "SSID_Settings_2",
    WifiInterface.GUEST_2G: "SSID_Settings_2_guest",
    WifiInterface.MAIN_5G: "SSID_Settings_5",
    WifiInterface.GUEST_5G: "SSID_Settings_5_guest",
}
_MODES = {
    WifiBand.GHZ_2_4: (WifiMode.BE_AX_N_G_B, WifiMode.AX_N_G_B, WifiMode.N_G_B, WifiMode.G_B),
    WifiBand.GHZ_5: (WifiMode.BE_AX_AC_N_A, WifiMode.AX_AC_N_A, WifiMode.AC_N_A, WifiMode.N_A),
}
_BANDWIDTHS = {
    WifiBand.GHZ_2_4: (WifiBandwidth.AUTO, WifiBandwidth.MHZ_20),
    WifiBand.GHZ_5: (
        WifiBandwidth.MHZ_160,
        WifiBandwidth.MHZ_80,
        WifiBandwidth.MHZ_40,
        WifiBandwidth.MHZ_20,
    ),
}
_BANDWIDTH_2G_CFG = {"0": "20MHz", "5": "Auto(20/40MHz)"}  # initWifiConfig, default Auto
_BANDWIDTH_2G_DEFAULT = "Auto(20/40MHz)"
_BANDWIDTH_5G_CFG = {"0": "20MHz", "1": "40MHz", "2": "80MHz", "3": "160MHz"}  # default 80


@dataclass(frozen=True, slots=True, kw_only=True)
class WifiNetwork:
    """One SSID (main or guest network of a band), decoded."""

    interface: WifiInterface
    enabled: bool
    """SSID enabled and its band's radio on (what the UI's on/off switch shows)."""
    ssid: str
    passphrase: str
    security: str
    """``Security_Mode`` (see :class:`WifiSecurity`)."""
    cipher: str | None
    hidden: bool
    max_devices: int | None
    wps_enabled: bool
    instance: int | None
    raw: Mapping[str, Any] = _raw()


@dataclass(frozen=True, slots=True, kw_only=True)
class WifiRadio:
    """Radio settings of one band."""

    band: WifiBand
    enabled: bool
    mode: str
    """802.11 mode (see :class:`WifiMode`)."""
    bandwidth: str
    """Channel width (see :class:`WifiBandwidth`)."""
    channel: int
    """0 = automatic."""
    channels: tuple[int, ...]
    """Channels the UI offers for this band."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WifiSettings:
    """Wi-Fi configuration as shown by the ``wifi-settings`` page."""

    radios: tuple[WifiRadio, ...]
    networks: tuple[WifiNetwork, ...]
    mlo_enabled: bool
    """Multi-Link Operation: one SSID across bands (2.4 GHz main mirrors 5 GHz main)."""
    mesh_controller: bool
    wps_enabled: bool
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def network(self, interface: WifiInterface) -> WifiNetwork:
        """Return the network of an interface."""
        return next(n for n in self.networks if n.interface is interface)


def js_decode_uri_component(value: str) -> str:
    """JS ``decodeURIComponent``: raises ``ValueError`` where JS throws ``URIError``."""
    if _MALFORMED_ESCAPE_RE.search(value):
        msg = f"malformed URI escape in {value!r}"
        raise ValueError(msg)
    try:
        return unquote(value, errors="strict")
    except UnicodeDecodeError as err:
        msg = f"invalid UTF-8 escape in {value!r}"
        raise ValueError(msg) from err


def _js_is_one(value: Any) -> bool:
    """JS ``value == 1`` for the number / string / boolean flags of the page."""
    if isinstance(value, bool):
        return value
    try:
        return float(str(value).strip() or "nan") == 1
    except ValueError:
        return False


def _js_number(value: Any) -> float:
    """JS numeric coercion of a page value (``NaN`` when not a number)."""
    if isinstance(value, bool):
        return float(value)
    try:
        return float(str(value).strip() or "0") if value is not None else float("nan")
    except ValueError:
        return float("nan")


def _js_length(value: str) -> int:
    """JS ``String.length`` (UTF-16 code units)."""
    return len(value.encode("utf-16-le")) // 2


def _passphrase_ok(passphrase: str) -> bool:
    """UI ``wifiPasswordCheck``: no forbidden symbol, at most 2 missing classes."""
    if _PASSPHRASE_FORBIDDEN_RE.search(passphrase):
        return False
    missing = sum(
        not re.search(pattern, passphrase)
        for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", _PASSPHRASE_SYMBOL_RE.pattern)
    )
    return missing <= 2


def _no_percent(what: str, value: str) -> None:
    if "%" in value:
        invalid(f"the {what} contains '%': the web UI URI-decodes it, so it cannot be set")


def _load_lists(html: str) -> dict[str, list[dict[str, Any]]]:
    lists: dict[str, list[dict[str, Any]]] = {}
    for match in _WIFI_LIST_RE.finditer(html):
        data = json.loads(match.group(2).replace("&quot;", '"'))
        lists.update(data)
    missing = set(_INTERFACE_LIST.values()) - set(lists)
    if missing:
        msg = f"Wi-Fi page lacks {sorted(missing)}"
        raise Id525ResponseError(msg)
    return lists


def _decoded(entry: Mapping[str, Any], key: str) -> str:
    try:
        return js_decode_uri_component(str(entry.get(key, "")))
    except ValueError as err:
        msg = f"the web UI cannot decode {key} of the Wi-Fi page: {err}"
        raise Id525ResponseError(msg) from err


@dataclass
class _UiState:
    """The ``wifi-settings`` page's JS state, after ``bodyLoad``."""

    lists: dict[str, list[dict[str, Any]]]
    cur_radio: str
    cur_interface: dict[WifiBand, str]
    bandwidth: dict[WifiBand, str]
    channel: dict[WifiBand, str]
    mode: dict[WifiBand, str]
    radio_status: dict[WifiInterface, bool]
    mlo: int
    mesh: int
    wps_cfg: bool
    wps: bool
    original_security: dict[WifiBand, str]
    channels: dict[WifiBand, tuple[int, ...]]

    @classmethod
    def from_page(cls, html: str) -> _UiState:
        values = extract_js_values(html)
        numbers = {m.group(1): int(m.group(2)) for m in _NUMERIC_VAR_RE.finditer(html)}
        arrays = {
            m.group(1): tuple(int(c) for c in m.group(2).split(",") if c.strip())
            for m in _ARRAY_VAR_RE.finditer(html)
        }
        lists = _load_lists(html)
        original_security = {
            WifiBand.GHZ_2_4: str(lists["SSID_Settings_2"][0].get("Security_Mode")),
            WifiBand.GHZ_5: str(lists["SSID_Settings_5"][0].get("Security_Mode")),
        }
        for entries in lists.values():  # bodyLoad: decodeURIComponent SSID / passphrase
            for entry in entries:
                entry["SSID"] = _decoded(entry, "SSID")
                entry["KeyPassphrase"] = _decoded(entry, "KeyPassphrase")
        radio_on = {
            WifiBand.GHZ_2_4: values.get("radioStatus2G") == "1",
            WifiBand.GHZ_5: values.get("radioStatus5G") == "1",
        }
        channel_cfg = {
            WifiBand.GHZ_2_4: values.get("channel2G_cfg", "0"),
            WifiBand.GHZ_5: values.get("channel5G_cfg", "0"),
        }
        state = cls(
            lists=lists,
            cur_radio=values.get("curRadio", WifiBand.GHZ_2_4.value),
            cur_interface={
                WifiBand.GHZ_2_4: values.get("curInterface2G", WifiInterface.MAIN_2G.value),
                WifiBand.GHZ_5: values.get("curInterface5G", WifiInterface.MAIN_5G.value),
            },
            bandwidth={
                WifiBand.GHZ_2_4: _BANDWIDTH_2G_CFG.get(
                    values.get("bandwidth2G", ""), _BANDWIDTH_2G_DEFAULT
                ),
                WifiBand.GHZ_5: _BANDWIDTH_5G_CFG.get(values.get("bandwidth5G", ""), "80MHz"),
            },
            channel={
                band: "Auto" if cfg.strip() in ("0", "") else f"Ch {cfg}"
                for band, cfg in channel_cfg.items()
            },
            mode={
                WifiBand.GHZ_2_4: values.get("curWiFiMode2G", ""),
                WifiBand.GHZ_5: values.get("curWiFiMode5G", ""),
            },
            radio_status={
                iface: _js_is_one(lists[key][0].get("SSID_Enable")) and radio_on[iface.band]
                for iface, key in _INTERFACE_LIST.items()
            },
            mlo=numbers.get("mloEnabled", 0),
            mesh=numbers.get("meshCtrlEnabled", 0),
            wps_cfg=values.get("wpsStatus_cfg") == "1",
            wps=values.get("wpsStatus_cfg") == "1",
            original_security=original_security,
            channels={
                WifiBand.GHZ_2_4: arrays.get("channel2G", ()),
                WifiBand.GHZ_5: arrays.get("channel5G", ()),
            },
        )
        state.check_interface(state.cur_radio)  # onScreenWidthChange -> selectObj(radio)
        return state

    # -- helpers ------------------------------------------------------------------

    def entry(self, interface: WifiInterface | str) -> dict[str, Any]:
        return self.lists[_INTERFACE_LIST[WifiInterface(interface)]][0]

    @property
    def mirrored(self) -> bool:
        return self.mlo == 1 or self.mesh == 1

    @property
    def target(self) -> WifiInterface:
        """The network the UI's inputs edit (``curRadio`` + its ``curInterface``)."""
        return WifiInterface(self.cur_interface[WifiBand(self.cur_radio)])

    def copy_5g_main_to_2g_main(self) -> None:
        main2, main5 = self.entry(WifiInterface.MAIN_2G), self.entry(WifiInterface.MAIN_5G)
        for key in ("SSID", "Security_Mode", "Cypher", "KeyPassphrase"):
            main2[key] = main5[key]

    def set_mirrored(self, key: str, value: Any) -> None:
        """Set a field of the target network, mirrored between main networks if MLO."""
        target = self.target
        self.entry(target)[key] = value
        if target.is_main and self.mirrored:
            other = (
                WifiInterface.MAIN_5G if target is WifiInterface.MAIN_2G else WifiInterface.MAIN_2G
            )
            self.entry(other)[key] = value

    # -- UI handlers ----------------------------------------------------------------

    def check_interface(self, radio: str) -> None:
        """``checkInterface``: with MLO, showing 2.4 GHz main copies the 5 GHz main."""
        if (
            radio == WifiBand.GHZ_2_4.value
            and "Main" in self.cur_interface[WifiBand.GHZ_2_4]
            and self.mirrored
        ):
            self.copy_5g_main_to_2g_main()

    def select_radio(self, band: WifiBand) -> None:
        self.check_interface(band.value)
        self.cur_radio = band.value

    def select_interface(self, interface: WifiInterface) -> None:
        if not interface.is_main and self.mesh == 1:
            invalid(f"{interface} is not offered while the mesh controller is enabled")
        self.cur_interface[WifiBand(self.cur_radio)] = interface.value
        self.check_interface(self.cur_radio)

    def radio_check(self, enabled: bool) -> None:  # noqa: FBT001
        self.radio_status[self.target] = enabled

    def ssid_input(self, ssid: str) -> None:
        _no_percent("SSID", ssid)
        self.set_mirrored("SSID", ssid)

    def security_set(self, security: WifiSecurity) -> None:
        self.set_mirrored("Security_Mode", security.value)
        self.set_mirrored("Cypher", "NONE" if security is WifiSecurity.OPEN else "AES")

    def password_input(self, passphrase: str) -> None:
        _no_percent("passphrase", passphrase)
        self.set_mirrored("KeyPassphrase", passphrase)

    def max_number_input(self, max_devices: int) -> None:
        """``wifiMaxNumberInput``: the text box clamps above 64 and keeps 2 chars."""
        text = "64" if max_devices > MAX_MAX_DEVICES else str(max_devices)
        self.entry(self.target)["MaxDevices"] = int(text[:2])

    def hidden_check(self, hidden: bool) -> None:  # noqa: FBT001
        self.entry(self.target)["SSID_Hidden"] = 1 if hidden else 0

    def mlo_check(self, enabled: bool) -> None:  # noqa: FBT001
        if enabled:
            self.mlo, self.mesh = 1, 0
            if self.mirrored:  # syncRadioSettings
                self.copy_5g_main_to_2g_main()
            self.mode[WifiBand.GHZ_5] = WifiMode.BE_AX_AC_N_A.value
            self.mode[WifiBand.GHZ_2_4] = WifiMode.BE_AX_N_G_B.value
        else:
            self.mlo = 0

    def select_mode(self, mode: WifiMode) -> None:
        band = WifiBand(self.cur_radio)
        if mode not in _MODES[band]:
            invalid(f"{mode} is not a {band} mode")
        required = _MODES[band][0]
        if self.mlo == 1 and mode is not required:
            invalid(f"with MLO enabled the {band} mode must be {required}")
        if band is WifiBand.GHZ_2_4:
            self.mode[band] = mode.value
            if mode is WifiMode.G_B:
                self.bandwidth[band] = WifiBandwidth.MHZ_20.value
        else:
            if mode is WifiMode.N_A:
                self.bandwidth[band] = WifiBandwidth.MHZ_40.value
            self.mode[band] = mode.value

    def select_bandwidth(self, bandwidth: WifiBandwidth) -> None:
        band = WifiBand(self.cur_radio)
        if bandwidth not in _BANDWIDTHS[band]:
            invalid(f"{bandwidth} is not offered on {band}")
        if band is WifiBand.GHZ_2_4:
            self.bandwidth[band] = bandwidth.value
            if bandwidth is WifiBandwidth.AUTO and self.mode[band] == WifiMode.G_B.value:
                self.mode[band] = WifiMode.BE_AX_N_G_B.value
            return
        channel = self.channel[band]
        if channel == "Ch 140":
            self.bandwidth[band] = WifiBandwidth.MHZ_20.value
        elif channel in ("Ch 132", "Ch 136") and bandwidth in (
            WifiBandwidth.MHZ_80,
            WifiBandwidth.MHZ_160,
        ):
            self.bandwidth[band] = WifiBandwidth.MHZ_40.value
        else:
            self.bandwidth[band] = bandwidth.value
        if bandwidth in (WifiBandwidth.MHZ_160, WifiBandwidth.MHZ_80) and (
            self.mode[band] == WifiMode.N_A.value
        ):
            self.mode[band] = WifiMode.BE_AX_AC_N_A.value

    def select_channel(self, channel: int) -> None:
        band = WifiBand(self.cur_radio)
        if channel != 0 and channel not in self.channels[band]:
            invalid(f"channel {channel} is not offered on {band}")
        text = "Auto" if channel == 0 else f"Ch {channel}"
        self.channel[band] = text
        if band is WifiBand.GHZ_5:
            if text == "Ch 140":
                self.bandwidth[band] = WifiBandwidth.MHZ_20.value
            elif text in ("Ch 132", "Ch 136") and self.bandwidth[band] in ("80MHz", "160MHz"):
                self.bandwidth[band] = WifiBandwidth.MHZ_40.value

    # -- save -----------------------------------------------------------------------

    def save_body(self, token: str | None) -> dict[str, Any]:
        """``wifiSettingSave``: validation chain, then the request (mutates the lists)."""
        lists = self.lists
        if self.mirrored:
            self.copy_5g_main_to_2g_main()
        order = list(_INTERFACE_LIST)
        for iface in order:
            entry = self.entry(iface)
            entry["SSID_Enable"] = 1 if self.radio_status[iface] else 0
        for iface in order:
            entry = self.entry(iface)
            for key in ("SSID", "KeyPassphrase"):
                try:
                    entry[key] = js_decode_uri_component(str(entry[key]))
                except ValueError:
                    invalid(f"the web UI cannot save {iface}: {key} is not URI-decodable")
        self._validate(order)
        body: dict[str, Any] = {
            TOKEN_FIELD: token,
            "meshCtrlEnabled": self.mesh,
            "mloEnabled": self.mlo,
        }
        bw2 = self.bandwidth[WifiBand.GHZ_2_4]
        body["Bandwidth2G"] = 5 if "Auto" in bw2 else 0 if "20" in bw2 else 1 if "40" in bw2 else 5
        body["WiFiMode2G"] = self.mode[WifiBand.GHZ_2_4]
        body["Channel2G"] = _channel_number(self.channel[WifiBand.GHZ_2_4])
        body["Bandwidth5G"] = _bandwidth_5g_number(self.bandwidth[WifiBand.GHZ_5])
        body["WiFiMode5G"] = self.mode[WifiBand.GHZ_5]
        body["Channel5G"] = _channel_number(self.channel[WifiBand.GHZ_5])
        for key in _INTERFACE_LIST.values():
            body[key] = lists[key]
        return body

    def _validate(self, order: list[WifiInterface]) -> None:
        """Run the UI's else-if chain (only the first matching condition counts)."""
        for iface in order:
            if not 0 < _js_length(str(self.entry(iface)["SSID"])) <= MAX_SSID_LENGTH:
                invalid(f"the SSID of {iface} must be 1-{MAX_SSID_LENGTH} characters")
        chain_stopped = False
        for iface in order:
            entry = self.entry(iface)
            length = _js_length(str(entry["KeyPassphrase"]))
            if not MIN_PASSPHRASE_LENGTH <= length <= MAX_PASSPHRASE_LENGTH:
                if _js_is_one(entry["SSID_Enable"]) and entry["Security_Mode"] != "OPEN":
                    invalid(
                        f"the passphrase of {iface} must be "
                        f"{MIN_PASSPHRASE_LENGTH}-{MAX_PASSPHRASE_LENGTH} characters"
                    )
                chain_stopped = True
                break
        if not chain_stopped:
            for iface in order:
                entry = self.entry(iface)
                devices = _js_number(entry["MaxDevices"])
                if devices < MIN_MAX_DEVICES or devices > MAX_MAX_DEVICES:
                    if _js_is_one(entry["SSID_Enable"]):
                        invalid(
                            f"the maximum number of devices of {iface} must be "
                            f"{MIN_MAX_DEVICES}-{MAX_MAX_DEVICES}"
                        )
                    break
        for iface in order:
            entry = self.entry(iface)
            if _js_is_one(entry["SSID_Enable"]) and not _passphrase_ok(str(entry["KeyPassphrase"])):
                invalid(
                    f"the passphrase of {iface} is too weak or contains one of '\"`%&+;:,<>? "
                    "(it needs at least two of: lowercase, uppercase, digit, symbol)"
                )


def _bandwidth_5g_number(text: str) -> int:
    """``wifiSettingSave``'s 5 GHz mapping (note: tested in this order)."""
    if "80" in text:
        return 2
    if "20" in text:
        return 0
    if "40" in text:
        return 1
    if "160" in text:
        return 3
    return 2


def _channel_number(text: str) -> int:
    return 0 if text == "Auto" else int(text.split(" ")[1])


def parse_wifi_page(html: str) -> WifiSettings:
    """Parse the data the router embeds in ``wifi-settings.html`` (no UI side effects)."""
    state = _UiState.from_page(html)
    pristine = _load_lists(html)
    networks = []
    for iface, key in _INTERFACE_LIST.items():
        entry = pristine[key][0]
        devices = str(entry.get("MaxDevices"))
        instance = str(entry.get("Instance"))
        networks.append(
            WifiNetwork(
                interface=iface,
                enabled=state.radio_status[iface],
                ssid=_decoded(entry, "SSID"),
                passphrase=_decoded(entry, "KeyPassphrase"),
                security=str(entry.get("Security_Mode", "")),
                cipher=str(entry["Cypher"]) if entry.get("Cypher") is not None else None,
                hidden=_js_is_one(entry.get("SSID_Hidden")),
                max_devices=int(devices) if devices.lstrip("-").isdigit() else None,
                wps_enabled=_js_is_one(entry.get("WPS_Enable")),
                instance=int(instance) if instance.isdigit() else None,
                raw=entry,
            )
        )
    values = extract_js_values(html)
    radios = tuple(
        WifiRadio(
            band=band,
            enabled=values.get(f"radioStatus{suffix}") == "1",
            mode=state.mode[band],
            bandwidth=state.bandwidth[band],
            channel=_channel_number(state.channel[band]),
            channels=state.channels[band],
        )
        for band, suffix in ((WifiBand.GHZ_2_4, "2G"), (WifiBand.GHZ_5, "5G"))
    )
    return WifiSettings(
        radios=radios,
        networks=tuple(networks),
        mlo_enabled=state.mlo == 1,
        mesh_controller=state.mesh == 1,
        wps_enabled=state.wps_cfg,
        raw={"lists": pristine},
    )


class WifiApi(Section):
    """Wi-Fi radios, networks, MLO and WPS."""

    @uses(Page.WIFI_SETTINGS)
    async def get_settings(self) -> WifiSettings:
        """Return radios, networks (SSIDs and passphrases), MLO and WPS state."""
        return parse_wifi_page(await self._client._page(Page.WIFI_SETTINGS))

    async def _load(self) -> _UiState:
        return _UiState.from_page(await self._client._page(Page.WIFI_SETTINGS))

    async def _save(self, state: _UiState) -> None:
        """``wifiSettingSave``.

        Like the UI, a mesh controller with WPS off first re-applies the WPS
        setting, *then* validates; otherwise nothing is sent on refusal.
        """
        if state.mesh == 1 and not state.wps_cfg:
            # The UI first (re)applies the WPS checkbox, which is still the stored value.
            wps = state.wps

            def wps_body(token: str | None) -> dict[str, Any]:
                return {TOKEN_FIELD: token, "wpsStatus": wps}

            data = await self._client._call(Endpoint.WPS_SETTING, wps_body)
            if not data.get("result"):
                raise Id525CommandError(Endpoint.WPS_SETTING, data.get("error"))
        body = state.save_body(None)  # once: saving URI-decodes the lists again

        def with_token(token: str | None) -> dict[str, Any]:
            return {**body, TOKEN_FIELD: token}

        await self._client._command(Endpoint.WIFI_SETTING, with_token)

    @uses(Page.WIFI_SETTINGS, Endpoint.WIFI_SETTING, Endpoint.WPS_SETTING)
    async def update_network(
        self,
        interface: WifiInterface,
        *,
        enabled: bool | None = None,
        ssid: str | None = None,
        security: WifiSecurity | None = None,
        passphrase: str | None = None,
        max_devices: int | None = None,
        hidden: bool | None = None,
    ) -> None:
        """Change one network (SSID) and save the whole Wi-Fi configuration.

        Omitted fields are kept. With MLO enabled, SSID, security and
        passphrase of the two main networks are always the same (editing one
        edits both, like the UI). ``max_devices`` above 64 is clamped to 64
        like the UI's input box. Changing Wi-Fi drops connected wireless
        clients while the router applies it.
        """
        interface = WifiInterface(interface)
        state = await self._load()
        state.select_radio(interface.band)
        state.select_interface(interface)
        if enabled is not None:
            state.radio_check(enabled)
        if ssid is not None:
            state.ssid_input(ssid)
        if security is not None:
            state.security_set(WifiSecurity(security))
        if passphrase is not None:
            state.password_input(passphrase)
        if max_devices is not None:
            state.max_number_input(max_devices)
        if hidden is not None:
            state.hidden_check(hidden)
        await self._save(state)

    @uses(Page.WIFI_SETTINGS, Endpoint.WIFI_SETTING, Endpoint.WPS_SETTING)
    async def update_radio(
        self,
        band: WifiBand,
        *,
        mode: WifiMode | None = None,
        bandwidth: WifiBandwidth | None = None,
        channel: int | None = None,
    ) -> None:
        """Change mode, channel width and channel (0 = auto) of a band, then save.

        Applied in this order with the UI's couplings: 802.11g/b forces 20 MHz
        on 2.4 GHz (and Auto width brings it back to be/ax/n/g/b), 802.11n/a
        forces 40 MHz on 5 GHz (and 80/160 MHz bring it back to be/ax/ac/n/a).
        With MLO enabled only the be modes are allowed.
        """
        state = await self._load()
        state.select_radio(WifiBand(band))
        if mode is not None:
            state.select_mode(WifiMode(mode))
        if bandwidth is not None:
            state.select_bandwidth(WifiBandwidth(bandwidth))
        if channel is not None:
            state.select_channel(channel)
        await self._save(state)

    @uses(Page.WIFI_SETTINGS, Endpoint.WIFI_SETTING, Endpoint.WPS_SETTING)
    async def set_mlo(self, enabled: bool) -> None:  # noqa: FBT001
        """Enable or disable Multi-Link Operation, then save.

        Enabling it copies the 5 GHz main network onto the 2.4 GHz one and
        sets both bands to their 802.11be mode, like the UI.
        """
        state = await self._load()
        state.mlo_check(enabled)
        await self._save(state)

    @uses(Endpoint.WPS_SETTING)
    async def set_wps(self, enabled: bool) -> None:  # noqa: FBT001
        """Enable or disable WPS."""

        def body(token: str | None) -> dict[str, Any]:
            return {TOKEN_FIELD: token, "wpsStatus": enabled}

        await self._client._command(Endpoint.WPS_SETTING, body)

    @uses(Page.WIFI_SETTINGS, Endpoint.WPS_START, Endpoint.WPS_CHECK)
    async def start_wps(self, *, poll_interval: float = 1.0) -> WpsResult:
        """Open a WPS pairing window and wait for its outcome (like the UI).

        Refused when WPS is disabled, or when both main networks use WPA3 only
        (WPS does not support it). Polls the router every ``poll_interval``
        seconds until it reports success, failure or timeout; a router that
        refuses to start or answers a poll with ``result: false`` yields
        :attr:`WpsResult.FAILED`, as the UI shows.
        """
        state = await self._load()
        if (
            state.original_security[WifiBand.GHZ_2_4] == WifiSecurity.WPA3
            and state.original_security[WifiBand.GHZ_5] == WifiSecurity.WPA3
        ):
            invalid("WPS is not available while both main networks use WPA3")
        if not state.wps_cfg:
            invalid("WPS is disabled: enable it first (set_wps)")
        if not (await self._client._call(Endpoint.WPS_START)).get("result"):
            return WpsResult.FAILED
        for _ in range(MAX_WPS_POLLS):
            await asyncio.sleep(poll_interval)
            data = await self._client._call(Endpoint.WPS_CHECK)
            if not data.get("result"):
                return WpsResult.FAILED
            status = str(data.get("wpsStatus"))
            if status in ("1", "2", "3"):
                return WpsResult(int(status))
            if status != "0":  # the UI stops polling and shows nothing
                msg = f"unknown WPS status {status!r}"
                raise Id525ResponseError(msg)
        msg = "the router never ended the WPS session"
        raise Id525ResponseError(msg)

    @uses(Endpoint.WPS_STOP)
    async def stop_wps(self) -> None:
        """Close a WPS pairing window."""
        await self._client._command(Endpoint.WPS_STOP, lambda token: {TOKEN_FIELD: token})
