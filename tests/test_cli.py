from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestServer

from id525 import Id525AuthenticationError, Id525ConfirmationRequiredError, Id525ReadOnlyError
from id525.cli import (
    COMMANDS,
    build_parser,
    cli_operations,
    load_env_file,
    main,
    negative_flag,
    parse_args,
    run,
    to_jsonable,
)
from id525.cli import (
    credentials as cli_credentials,
)
from id525.operations import operations
from id525.parsers import parse_network_status, parse_sms

from .conftest import MUTATING, PASSWORD, USERNAME, FakeRouter, load_fixture


def test_to_jsonable_models_are_json_serialisable() -> None:
    status = to_jsonable(parse_network_status(json.loads(load_fixture("net_status.json"))))
    sms = to_jsonable(parse_sms(json.loads(load_fixture("sms_reload.json"))))
    assert status["sim_state"] == "Connected"
    assert status["connection_duration"] == 37 * 86400 + 10 * 3600 + 55 * 60 + 44
    assert status["statistics_reset_date"] == "2025-08-20"
    assert "raw" not in status
    assert sms["messages"][0]["time"] == "2026-10-01T08:15:00"
    json.dumps([status, sms])


def test_load_env_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\nID525_USERNAME=admin\nID525_PASSWORD='p=ss'\n\n")
    assert load_env_file(env) == {"ID525_USERNAME": "admin", "ID525_PASSWORD": "p=ss"}


def test_parser_rejects_unknown_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["reboot"])


def test_main_reports_connection_errors(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ID525_PASSWORD", PASSWORD)
    assert main(["--host", "127.0.0.1:9", "status"]) == 1
    assert "failed" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["status"], ["lan", "get-settings"]])
async def test_no_password_is_refused_before_any_request(
    server: TestServer,
    router: FakeRouter,
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    monkeypatch.delenv("ID525_PASSWORD", raising=False)
    with pytest.raises(Id525AuthenticationError, match="no password"):
        await run(cli_args(server, *argv))
    assert router.calls == []


def test_env_file_may_use_plain_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ID525_USERNAME", raising=False)
    monkeypatch.delenv("ID525_PASSWORD", raising=False)
    monkeypatch.setenv("USERNAME", "system-login")  # never taken from the environment
    env = tmp_path / ".env"
    env.write_text("USERNAME=boss\nPASSWORD=s3cret\n")
    assert cli_credentials(parse_args(["--env-file", str(env), "status"])) == ("boss", "s3cret")
    monkeypatch.setenv("ID525_PASSWORD", "from-env")
    assert cli_credentials(parse_args(["--env-file", str(env), "status"])) == ("boss", "from-env")


def test_quick_reads_still_parse() -> None:
    args = parse_args(["--host", "h", "status", "clients"])
    assert args.commands == ["status", "clients"]


def test_every_implemented_operation_is_reachable_from_the_cli() -> None:
    session_plumbing = {"login", "logout", "ensure_session", "keep_alive"}
    quick = {f.__name__ for f in COMMANDS.values()}
    via_sections = {op.path for ops in cli_operations().values() for op in ops.values()}
    for op in operations():
        if not op.implemented or op.name in session_plumbing:
            continue
        assert op.path in via_sections or (op.section is None and op.name in quick), op.path


def cli_args(server: TestServer, *argv: str) -> Any:
    return parse_args(["--scheme", "http", "--host", f"{server.host}:{server.port}", *argv])


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ID525_USERNAME", USERNAME)
    monkeypatch.setenv("ID525_PASSWORD", PASSWORD)


@pytest.mark.usefixtures("credentials")
async def test_section_read(server: TestServer, router: FakeRouter) -> None:
    result = await run(cli_args(server, "lan", "get-settings"))
    assert result["dhcp_start"] == "192.168.224.20"
    assert len(result["reservations"]) == 3
    assert router.count("logout_req") == 1


@pytest.mark.usefixtures("credentials")
async def test_multi_word_sections_are_hyphenated(server: TestServer) -> None:
    assert all("_" not in name for name in cli_operations())
    result = await run(cli_args(server, "port-forwarding", "get-settings"))
    assert "rules" in result


@pytest.mark.usefixtures("credentials")
async def test_write_needs_the_write_flag(server: TestServer, router: FakeRouter) -> None:
    argv = ["lan", "delete-dhcp-reservation", "--index", "7"]
    with pytest.raises(Id525ReadOnlyError):
        await run(cli_args(server, *argv))
    assert router.calls == []
    assert await run(cli_args(server, "--write", *argv)) == {"ok": True}
    assert router.count("req_LanStaticAddrDelete") == 1


@pytest.mark.usefixtures("credentials")
async def test_destructive_needs_confirm(server: TestServer, router: FakeRouter) -> None:
    with pytest.raises(Id525ConfirmationRequiredError):
        await run(cli_args(server, "--write", "system", "reboot"))
    assert router.calls == []
    assert await run(cli_args(server, "--write", "system", "reboot", "--confirm")) == {"ok": True}
    assert router.count("reboot") == 1


def test_optional_arguments_default_to_none() -> None:
    args = parse_args(["lan", "modify-dhcp-reservation", "--index", "1", "--ip", "192.168.224.30"])
    assert (args.index, args.ip, args.name, args.mac) == (1, "192.168.224.30", None, None)


def test_read_only_error_suggests_the_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--host", "127.0.0.1:9", "lan", "delete-dhcp-reservation", "--index", "1"]) == 1
    assert "add --write" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("name", "negative"),
    [
        ("enabled", "--disabled"),
        ("dhcp_enabled", "--dhcp-disabled"),
        ("line_enabled", "--line-disabled"),
        ("disabled", "--enabled"),
        ("hidden", "--no-hidden"),
    ],
)
def test_negative_flag(name: str, negative: str) -> None:
    assert negative_flag(name) == negative


def test_required_booleans_must_be_explicit(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(["wifi", "set-wps"])
    assert "--enabled --disabled is required" in capsys.readouterr().err
    assert parse_args(["wifi", "set-wps", "--disabled"]).enabled is False
    assert parse_args(["wifi", "set-wps", "--enabled"]).enabled is True
    with pytest.raises(SystemExit):
        parse_args(["wifi", "set-wps", "--enabled", "--disabled"])


def test_boolean_defaults_follow_the_api() -> None:
    assert parse_args(["cellular", "add-apn", "--apn", "x"]).enabled is True
    assert parse_args(["cellular", "add-apn", "--apn", "x", "--disabled"]).enabled is False
    unset = parse_args(["wifi", "update-network", "--interface", "5G_Main"])
    assert (unset.enabled, unset.hidden) == (None, None)  # left unchanged
    rule = ["port-forwarding", "add-rule", "--wan-port", "80", "--lan-ip", "192.168.224.9"]
    assert parse_args([*rule, "--lan-port", "80"]).disabled is False
    assert parse_args([*rule, "--lan-port", "80", "--disabled"]).disabled is True


@pytest.mark.usefixtures("credentials")
async def test_set_wps_disabled_reaches_the_router(server: TestServer, router: FakeRouter) -> None:
    assert await run(cli_args(server, "--write", "wifi", "set-wps", "--disabled")) == {"ok": True}
    sent = [json.loads(body) for name, body in router.bodies if name in MUTATING]
    assert len(sent) == 1
