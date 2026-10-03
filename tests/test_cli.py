from __future__ import annotations

import json
from pathlib import Path

import pytest

from id525.cli import build_parser, load_env_file, main, to_jsonable
from id525.parsers import parse_network_status, parse_sms

from .conftest import load_fixture


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
