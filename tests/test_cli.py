from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestServer

from id525 import Id525ConfirmationRequiredError, Id525ReadOnlyError
from id525.cli import (
    COMMANDS,
    build_parser,
    cli_operations,
    load_env_file,
    main,
    parse_args,
    run,
    to_jsonable,
)
from id525.operations import operations
from id525.parsers import parse_network_status, parse_sms

from .conftest import PASSWORD, USERNAME, FakeRouter, load_fixture


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


def test_main_reports_connection_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--host", "127.0.0.1:9", "status"]) == 1
    assert "error:" in capsys.readouterr().err


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
async def test_write_needs_the_write_flag(server: TestServer, router: FakeRouter) -> None:
    argv = ["lan", "delete-dhcp-reservation", "--index", "2"]
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
