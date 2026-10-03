"""Command line interface: ``id525 [--host H] <command>``.

Credentials come from ``ID525_USERNAME`` / ``ID525_PASSWORD`` (or an env file
given with ``--env-file``). Every command is read-only.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import enum
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .client import Id525Client
from .const import DEFAULT_HOST, DEFAULT_USERNAME
from .exceptions import Id525Error

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

COMMANDS: dict[str, Callable[[Id525Client], Awaitable[Any]]] = {
    "status": Id525Client.get_network_status,
    "clients": Id525Client.get_clients,
    "cells": Id525Client.get_cellular_info,
    "utilization": Id525Client.get_utilization,
    "about": Id525Client.get_device_info,
    "sms": Id525Client.get_sms,
    "session": Id525Client.get_login_state,
}


def to_jsonable(value: Any) -> Any:  # noqa: PLR0911
    """Convert models (dataclasses, enums, dates...) into JSON-friendly values."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: to_jsonable(getattr(value, f.name))
            for f in dataclasses.fields(value)
            if f.name != "raw"
        }
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    return value


def load_env_file(path: Path) -> dict[str, str]:
    """Parse a minimal ``KEY=value`` env file."""
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip().strip("'\"")
    return values


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="id525", description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=os.environ.get("ID525_HOST", DEFAULT_HOST))
    parser.add_argument("--env-file", type=Path, help="file with ID525_USERNAME/ID525_PASSWORD")
    parser.add_argument("commands", nargs="+", choices=[*COMMANDS, "all"], metavar="command")
    return parser


async def run(args: argparse.Namespace) -> dict[str, Any]:
    """Log in once, run the requested commands, log out."""
    env = {**(load_env_file(args.env_file) if args.env_file else {}), **os.environ}
    names = list(COMMANDS) if "all" in args.commands else args.commands
    async with Id525Client(
        args.host,
        env.get("ID525_USERNAME", DEFAULT_USERNAME),
        env.get("ID525_PASSWORD", ""),
    ) as client:
        return {name: to_jsonable(await COMMANDS[name](client)) for name in names}


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(run(args))
    except Id525Error as err:
        print(f"error: {err}", file=sys.stderr)  # noqa: T201
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
