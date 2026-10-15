"""Debug traces: complete (every exchange, errors) and redacted (no secrets, no identity)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestServer

from id525 import Endpoint, Id525ConnectionError
from id525.cli import main
from id525.trace import Redactor, TraceRecorder

from .conftest import PASSWORD, USERNAME, ClientFactory, FakeRouter


def redact(*texts: str) -> list[str]:
    recorder = TraceRecorder()
    for text in texts:
        recorder.record("x", body=text)
    return [e["body"] for e in recorder.redacted_events()[:-1]]


def test_credentials_and_tokens_become_stable_pseudonyms() -> None:
    login = '{"RequestVerifyToken":"a1b2c3d4","usr":"admin","pwd":"hunter22"}'
    answer = '{"result":true,"RequestVerifyToken":"e5f6a7b8"}'
    nxt = '{"RequestVerifyToken":"e5f6a7b8","lan_ip":"192.168.224.1"}'
    out = redact(login, answer, nxt)
    assert out[0] == '{"RequestVerifyToken":"TOKEN-1","usr":"admin","pwd":"SECRET-1"}'
    assert out[1] == '{"result":true,"RequestVerifyToken":"TOKEN-2"}'
    assert out[2] == '{"RequestVerifyToken":"TOKEN-2","lan_ip":"192.168.224.1"}'


def test_short_secrets_are_redacted_without_touching_substrings() -> None:
    out = redact('{"pwd":"123","pingCount":"123x","n":"0123"}', "123")
    assert out == ['{"pwd":"SECRET-1","pingCount":"123x","n":"0123"}', "SECRET-1"]


def test_session_cookie() -> None:
    out = redact("QSESSIONID=deadbeef42; path=/", "QSESSIONID=deadbeef42")
    assert out == ["QSESSIONID=SESSION-1; path=/", "QSESSIONID=SESSION-1"]


def test_identity_values_in_pages_and_nested_json() -> None:
    page = (
        'var curPassword = "87654321";\n'
        "var wifi = '{&quot;SSID&quot;:&quot;Home%5fNet&quot;,"
        "&quot;KeyPassphrase&quot;:&quot;s3cret-pass&quot;}';\n"
        'document.getElementById(platform + "-voip_account_text").value = '
        'decodeURIComponent("%2b390612345678");\n'
        'document.getElementById(platform + "-voip_outbound_proxy_text").value = "sip.example";\n'
    )
    nested = json.dumps({"staticAddrList_str": json.dumps({"deviceName": "Kitchen-TV"})})
    echo = "joined Home_Net from Kitchen-TV, number +390612345678, key s3cret-pass"
    out = "\n".join(redact(page, nested, echo))
    for secret in ("87654321", "Home", "s3cret", "390612345678", "sip.example", "Kitchen"):
        assert secret not in out, secret
    assert "SSID-1" in out
    assert "+000000000001" in out  # digits keep their length (parsers still work)


def test_rule_descriptions_are_redacted() -> None:
    # MAC filter / port forwarding rule names are user-chosen device names.
    page = (
        'var tmp = "[{&quot;instance&quot;:1,&quot;description&quot;:&quot;Anna-Phone&quot;,'
        '&quot;macAddress&quot;:&quot;aa:bb:cc:dd:ee:ff&quot;}]";'
    )
    body = '{"edit_instance":1,"desc":"Anna-Phone","clientMac":"aa:bb:cc:dd:ee:ff"}'
    out = "\n".join(redact(page, body))
    assert "Anna" not in out
    assert out.count("NAME-1") == 2


def test_patterns_without_keys() -> None:
    out = redact(
        "mac AA-BB-CC-11-22-33 imei 358000000000017 wan 93.184.216.34 lan 192.168.224.7 "
        "dns 8.8.8.8 v6 2a01:4f8:1:2::3 doc 02:00:5e:00:00:01"
    )[0]
    assert "AA-BB" not in out
    assert "358000000000017" not in out
    assert "93.184" not in out
    assert "2a01:4f8" not in out
    assert "192.168.224.7" in out
    assert "8.8.8.8" in out
    assert "02:00:5e:00:00:01" in out


def test_same_mac_in_any_spelling_gets_one_pseudonym() -> None:
    redactor = Redactor()
    redactor.learn('{"mac":"aa:bb:cc:dd:ee:ff"}')
    out = redactor.redact("AA:BB:CC:DD:EE:FF aa-bb-cc-dd-ee-ff aa:bb:cc:dd:ee:ff")
    assert out == "02:00:5e:10:00:01 " * 2 + "02:00:5e:10:00:01"


def test_unredacted_trace_keeps_everything() -> None:
    recorder = TraceRecorder(redact=False)
    recorder.record("x", body='{"pwd":"hunter22"}')
    assert recorder.redacted_events()[0]["body"] == '{"pwd":"hunter22"}'


async def test_client_traces_every_exchange(make_client: ClientFactory, router: FakeRouter) -> None:
    tracer = TraceRecorder(redact=False)
    client = await make_client(tracer=tracer)
    await client.get_network_status()
    await client.lan.get_settings()
    await client.close()
    http = [e for e in tracer.events if e["event"] == "http"]
    assert [(e["method"], e["path"].rsplit("/", 1)[-1]) for e in http] == [
        ("GET", ""),
        ("POST", "token_query.cgi"),
        ("POST", "login_req.cgi"),
        ("POST", "net_status_retrieve.cgi"),
        ("GET", "lan-settings.html"),
        ("POST", "logout_req.cgi"),
    ]
    posts = [e["request_body"] for e in http if e["method"] == "POST"]
    assert posts == [body.decode() for _, body in router.bodies]
    assert all(e["status"] == 200 and e["ms"] >= 0 for e in http)
    assert "dhcp_reservation_list" in http[4]["response_body"]


async def test_http_errors_keep_status_and_body(make_client: ClientFactory) -> None:
    tracer = TraceRecorder(redact=False)
    client = await make_client(tracer=tracer)
    with pytest.raises(Id525ConnectionError, match="404"):
        await client._call(Endpoint.DDNS_GET)
    failed = tracer.events[-1]
    assert failed["path"].endswith("ddns_get.cgi") or failed["status"] == 404
    assert failed["status"] == 404
    assert failed["error"].startswith("ClientResponseError")
    assert "response_body" in failed


# --- CLI ---------------------------------------------------------------------


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ID525_USERNAME", USERNAME)
    monkeypatch.setenv("ID525_PASSWORD", PASSWORD)
    monkeypatch.delenv("ID525_TRACE", raising=False)


async def run_main(server: TestServer, tmp_path: Path, *argv: str) -> tuple[int, list[Any]]:
    trace = tmp_path / "trace.jsonl"
    host = f"{server.host}:{server.port}"
    argv_full = ["--scheme", "http", "--host", host, "--trace-file", str(trace), *argv]
    code = await asyncio.to_thread(main, argv_full)
    return code, [json.loads(line) for line in trace.read_text().splitlines()]


def kinds(events: list[Any]) -> list[str]:
    return [e["event"] for e in events]


@pytest.mark.usefixtures("credentials")
async def test_cli_trace_of_a_read(
    server: TestServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, events = await run_main(server, tmp_path, "status")
    assert code == 0
    assert kinds(events)[0] == "start"
    assert kinds(events)[-2:] == ["result", "redaction"]
    assert events[0]["environment"]["python"]
    raw = json.dumps(events)
    assert PASSWORD not in raw
    assert '\\"pwd\\":\\"SECRET-1\\"' in raw
    assert "TOKEN-1" in raw
    assert f"trace: {tmp_path / 'trace.jsonl'}" in capsys.readouterr().err


@pytest.mark.usefixtures("credentials")
async def test_cli_trace_of_a_refusal(
    server: TestServer, router: FakeRouter, tmp_path: Path
) -> None:
    code, events = await run_main(
        server, tmp_path, "lan", "delete-dhcp-reservation", "--index", "7"
    )
    assert code == 1
    assert router.calls == []  # refused before logging in
    assert kinds(events) == ["start", "call", "error", "redaction"]
    assert events[2]["type"] == "id525.exceptions.Id525ReadOnlyError"
    assert events[1]["kwargs"] == {"index": 7}


@pytest.mark.usefixtures("credentials")
async def test_cli_trace_of_a_router_refusal(
    server: TestServer, router: FakeRouter, tmp_path: Path
) -> None:
    router.answers = {"req_LanStaticAddrDelete": {"result": False, "error": "busy"}}
    code, events = await run_main(
        server, tmp_path, "--write", "lan", "delete-dhcp-reservation", "--index", "7"
    )
    assert code == 1
    error = next(e for e in events if e["event"] == "error")
    assert error["type"] == "id525.exceptions.Id525CommandError"
    answer = next(e for e in events if e.get("path", "").endswith("req_LanStaticAddrDelete.cgi"))
    assert json.loads(answer["response_body"])["error"] == "busy"


@pytest.mark.usefixtures("credentials")
async def test_cli_trace_survives_unexpected_errors(
    server: TestServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(data: Any) -> Any:
        raise KeyError("ipv4_addr")

    monkeypatch.setattr("id525.client.parse_network_status", broken)
    with pytest.raises(KeyError):
        await run_main(server, tmp_path, "status")
    events = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    error = next(e for e in events if e["event"] == "error")
    assert error["type"] == "builtins.KeyError"
    assert any("broken" in line for line in error["traceback"])
    assert any(e.get("path", "").endswith("net_status_retrieve.cgi") for e in events)


@pytest.mark.usefixtures("credentials")
async def test_cli_trace_records_secret_arguments_redacted(
    server: TestServer, tmp_path: Path
) -> None:
    code, events = await run_main(
        server,
        tmp_path,
        "--write",
        "account",
        "change-password",
        "--current-password",
        PASSWORD,
        "--new-password",
        "N3w-Passw0rd!",
    )
    raw = json.dumps(events)
    assert PASSWORD not in raw
    assert "N3w-Passw0rd" not in raw
    assert code in (0, 1)


def test_default_trace_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from id525.cli import default_trace_path, parse_args

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    path = default_trace_path(parse_args(["lan", "get-settings"]))
    assert path.parent == tmp_path / "id525" / "traces"
    assert path.name.endswith("-lan-get-settings.jsonl")


def test_trace_file_value_is_not_taken_for_a_command() -> None:
    from id525.cli import parse_args

    args = parse_args(["--trace-file", "status", "lan", "get-settings"])
    assert args.section == "lan"
    assert args.trace_file == Path("status")


def test_only_public_wan_addresses_are_redacted() -> None:
    out = redact('{"ipv4_addr":"10.77.1.2","ipv6_addr":"2a01:4f8::1","ipv4_gw":"100.64.0.1"}')[0]
    assert out == '{"ipv4_addr":"10.77.1.2","ipv6_addr":"2001:db8::1","ipv4_gw":"100.64.0.1"}'
