"""Command line interface for every operation of the client.

Usage::

    id525 [--host H] [--env-file F] status clients ...       # quick reads
    id525 [--host H] [--write] <section> <operation> [--arg value ...]

Credentials come from ``ID525_USERNAME`` / ``ID525_PASSWORD`` (or an env file
given with ``--env-file``). Section commands are generated from the client API
(``id525 --help`` lists them). Operations that change the router need the
global ``--write`` flag, and destructive ones also ``--confirm``.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import enum
import inspect
import json
import os
import sys
import types
import typing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .client import Id525Client
from .const import DEFAULT_HOST, DEFAULT_USERNAME
from .exceptions import Id525Error
from .operations import Operation, operations

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
"""Quick read commands; several can be given at once (``all`` runs them all)."""


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


def cli_operations() -> dict[str, dict[str, Operation]]:
    """Return section -> command name -> operation, for implemented section operations."""
    found: dict[str, dict[str, Operation]] = {}
    for op in operations():
        if op.section is not None and op.implemented:
            found.setdefault(op.section, {})[op.name.replace("_", "-")] = op
    return found


def _base_type(hint: Any) -> Any:
    """Strip ``X | None`` to ``X``."""
    if isinstance(hint, types.UnionType) or typing.get_origin(hint) is typing.Union:
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        return args[0] if len(args) == 1 else str
    return hint


def _add_arguments(parser: argparse.ArgumentParser, op: Operation) -> None:
    hints = typing.get_type_hints(op.function)
    for name, param in inspect.signature(op.function).parameters.items():
        if name == "self":
            continue
        flag = f"--{name.replace('_', '-')}"
        kind = _base_type(hints.get(name, str))
        required = param.default is inspect.Parameter.empty
        if kind is bool and param.default is None:  # tri-state: unset / --x / --no-x
            parser.add_argument(flag, dest=name, action=argparse.BooleanOptionalAction)
        elif kind is bool:
            parser.add_argument(flag, dest=name, action="store_true", default=param.default is True)
        elif isinstance(kind, type) and issubclass(kind, enum.Enum):
            parser.add_argument(
                flag,
                dest=name,
                type=kind,
                choices=list(kind),
                required=required,
                default=None if required else param.default,
            )
        else:
            parser.add_argument(
                flag,
                dest=name,
                type=kind if kind in (int, float, str) else str,
                required=required,
                default=None if required else param.default,
            )


def build_parser() -> argparse.ArgumentParser:
    """Build the parser for section operations (quick reads are handled separately)."""
    parser = argparse.ArgumentParser(
        prog="id525",
        description=__doc__.splitlines()[0],
        epilog=f"quick reads: id525 {{{','.join([*COMMANDS, 'all'])}}} ...",
    )
    parser.add_argument("--host", default=os.environ.get("ID525_HOST", DEFAULT_HOST))
    parser.add_argument("--env-file", type=Path, help="file with ID525_USERNAME/ID525_PASSWORD")
    parser.add_argument(
        "--scheme", choices=["https", "http"], default="https", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="allow operations that change the router (the client is read-only otherwise)",
    )
    sections = parser.add_subparsers(dest="section", metavar="section", required=True)
    for section, ops in cli_operations().items():
        section_parser = sections.add_parser(section, help=f"{section} operations")
        commands = section_parser.add_subparsers(dest="command", metavar="command", required=True)
        for command, op in ops.items():
            doc = (inspect.getdoc(op.function) or "").splitlines()
            sub = commands.add_parser(
                command, help=doc[0] if doc else None, description=" ".join(doc) or None
            )
            _add_arguments(sub, op)
            sub.set_defaults(operation=op)
    return parser


def build_read_parser() -> argparse.ArgumentParser:
    """Build the parser for quick read commands."""
    parser = argparse.ArgumentParser(prog="id525", description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=os.environ.get("ID525_HOST", DEFAULT_HOST))
    parser.add_argument("--env-file", type=Path, help="file with ID525_USERNAME/ID525_PASSWORD")
    parser.add_argument(
        "--scheme", choices=["https", "http"], default="https", help=argparse.SUPPRESS
    )
    parser.add_argument("commands", nargs="+", choices=[*COMMANDS, "all"], metavar="command")
    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Dispatch to the quick-read parser or the section parser."""
    positional = [a for a in argv if not a.startswith("-")]
    # option values (--host H) are positional-looking: the first real command
    # is the first token that is a known read command or section name
    known = {*COMMANDS, "all"}
    first = next((a for a in positional if a in known | set(cli_operations())), None)
    if first in known:
        return build_read_parser().parse_args(argv)
    return build_parser().parse_args(argv)


def _client(args: argparse.Namespace, *, read_only: bool) -> Id525Client:
    env = {**(load_env_file(args.env_file) if args.env_file else {}), **os.environ}
    return Id525Client(
        args.host,
        env.get("ID525_USERNAME", DEFAULT_USERNAME),
        env.get("ID525_PASSWORD", ""),
        scheme=args.scheme,
        read_only=read_only,
    )


async def run(args: argparse.Namespace) -> Any:
    """Log in once, run the requested command(s), log out."""
    if hasattr(args, "commands"):
        names = list(COMMANDS) if "all" in args.commands else args.commands
        async with _client(args, read_only=True) as client:
            return {name: to_jsonable(await COMMANDS[name](client)) for name in names}
    op: Operation = args.operation
    kwargs = {
        name: getattr(args, name)
        for name in inspect.signature(op.function).parameters
        if name != "self"
    }
    client = _client(args, read_only=not args.write)
    for endpoint in op.endpoints:  # refuse before logging in
        client.check_allowed(endpoint, confirmed=kwargs.get("confirm") is True)
    async with client:
        method = getattr(getattr(client, args.section), op.name)
        result = await method(**kwargs)
    return {"ok": True} if result is None else to_jsonable(result)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = asyncio.run(run(args))
    except (Id525Error, NotImplementedError) as err:
        hint = " (add --write)" if "read_only=False" in str(err) else ""
        print(f"error: {err}{hint}", file=sys.stderr)  # noqa: T201
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
