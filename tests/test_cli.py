from __future__ import annotations

import asyncio
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


@pytest.mark.parametrize(
    ("argv", "path"),
    [
        (["sms", "mark-read", "--phone-number", "123"], "sms.mark_read"),
        (["--host", "h", "status", "get-sim-pin-status"], "status.get_sim_pin_status"),
    ],
)
def test_section_commands_win_over_quick_reads_of_the_same_name(argv: list[str], path: str) -> None:
    assert parse_args(argv).operation.path == path


def test_every_section_command_reaches_its_own_parser(capsys: pytest.CaptureFixture[str]) -> None:
    for section, commands in cli_operations().items():
        for command in commands:
            with pytest.raises(SystemExit):
                parse_args([section, command, "--help"])
            assert f"usage: id525 {section} {command}" in capsys.readouterr().out


def test_quick_reads_named_like_sections_still_parse() -> None:
    assert parse_args(["sms", "status"]).commands == ["sms", "status"]


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
    assert parse_args([*rule, "--lan-port", "80"]).enabled is True
    assert parse_args([*rule, "--lan-port", "80", "--disabled"]).enabled is False


@pytest.mark.usefixtures("credentials")
async def test_set_wps_disabled_reaches_the_router(server: TestServer, router: FakeRouter) -> None:
    assert await run(cli_args(server, "--write", "wifi", "set-wps", "--disabled")) == {"ok": True}
    sent = [json.loads(body) for name, body in router.bodies if name in MUTATING]
    assert len(sent) == 1


def _untested_firmware(router: FakeRouter) -> None:
    about = load_fixture("help-about.html").replace("ID525_REL_1.0.09.17", "ID525_REL_9.9.99.99")
    router.page_html["help-about"] = about


@pytest.mark.usefixtures("credentials")
async def test_writes_check_the_firmware_first(server: TestServer, router: FakeRouter) -> None:
    await run(cli_args(server, "--write", "wifi", "set-wps", "--disabled"))
    assert router.calls.index("page:help-about") < router.calls.index("req_wpsSetting")


@pytest.mark.usefixtures("credentials")
async def test_reads_do_not_check_the_firmware(server: TestServer, router: FakeRouter) -> None:
    await run(cli_args(server, "lan", "get-settings"))
    assert "page:help-about" not in router.calls


@pytest.mark.usefixtures("credentials")
@pytest.mark.parametrize("untested", [False, True])
async def test_untested_firmware_is_reported_on_stderr(
    server: TestServer, router: FakeRouter, capsys: pytest.CaptureFixture[str], untested: bool
) -> None:
    if untested:
        _untested_firmware(router)
    argv = ["--scheme", "http", "--host", f"{server.host}:{server.port}", "--write"]
    exit_code = await asyncio.to_thread(main, [*argv, "wifi", "set-wps", "--disabled"])
    assert exit_code == 0
    err = capsys.readouterr().err
    assert ("warning: Firmware ID525_REL_9.9.99.99 was never tested" in err) is untested
