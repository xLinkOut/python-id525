"""Command line interface for every operation of the client.

Usage::

    id525 [--host H] [--env-file F] status clients ...       # quick reads
    id525 [--host H] [--write] <section> <operation> [--arg value ...]

Credentials come from ``ID525_USERNAME`` / ``ID525_PASSWORD`` (or an env file
given with ``--env-file``). Section commands are generated from the client API
(``id525 --help`` lists them). Operations that change the router need the
global ``--write`` flag, and destructive ones also ``--confirm``.

``--trace`` (or ``ID525_TRACE=1``) saves a redacted JSON-lines trace of the run:
command, every HTTP request and raw answer, library log, result or traceback.
It is written even when the command fails, to ``--trace-file`` or to
``$XDG_CACHE_HOME/id525/traces/`` (default ``~/.cache``); the path goes to stderr.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import enum
import inspect
import json
import logging
import os
import platform
import subprocess
import sys
import traceback
import types
import typing
from datetime import UTC, date, datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .client import Id525Client
from .const import DEFAULT_HOST, DEFAULT_USERNAME
from .exceptions import Id525AuthenticationError, Id525Error
from .operations import Operation, operations
from .trace import TraceRecorder

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

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
            section = op.section.replace("_", "-")
            found.setdefault(section, {})[op.name.replace("_", "-")] = op
    return found


def _base_type(hint: Any) -> Any:
    """Strip ``X | None`` to ``X``."""
    if isinstance(hint, types.UnionType) or typing.get_origin(hint) is typing.Union:
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        return args[0] if len(args) == 1 else str
    return hint


def negative_flag(name: str) -> str:
    """Return the opposite of a boolean flag: ``--disabled``, ``--dhcp-disabled``, ``--no-x``."""
    if name.endswith("enabled"):
        return "--" + name.removesuffix("enabled").replace("_", "-") + "disabled"
    if name == "disabled":
        return "--enabled"
    return "--no-" + name.replace("_", "-")


def _add_arguments(parser: argparse.ArgumentParser, op: Operation) -> None:
    hints = typing.get_type_hints(op.function)
    for name, param in inspect.signature(op.function).parameters.items():
        if name == "self":
            continue
        flag = f"--{name.replace('_', '-')}"
        kind = _base_type(hints.get(name, str))
        required = param.default is inspect.Parameter.empty
        if kind is bool and name == "confirm":
            parser.add_argument(flag, dest=name, action="store_true")
        elif kind is bool:  # always an explicit pair: --enabled / --disabled
            group = parser.add_mutually_exclusive_group(required=required)
            group.add_argument(flag, dest=name, action="store_true")
            group.add_argument(negative_flag(name), dest=name, action="store_false")
            parser.set_defaults(**{name: None if required else param.default})
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


VALUE_OPTIONS = frozenset({"--host", "--env-file", "--scheme", "--trace-file"})
"""Global options followed by a value (skipped when looking for the command)."""


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=os.environ.get("ID525_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--env-file",
        type=Path,
        help="file with ID525_USERNAME/ID525_PASSWORD (or USERNAME/PASSWORD)",
    )
    parser.add_argument(
        "--scheme", choices=["https", "http"], default="https", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        default=os.environ.get("ID525_TRACE", "") not in ("", "0"),
        help="save a redacted trace of the run (requests, answers, errors) for debugging",
    )
    parser.add_argument("--trace-file", type=Path, help="where to save the trace (implies --trace)")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="print the library debug log to stderr"
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the parser for section operations (quick reads are handled separately)."""
    parser = argparse.ArgumentParser(
        prog="id525",
        description=__doc__.splitlines()[0],
        epilog=f"quick reads: id525 {{{','.join([*COMMANDS, 'all'])}}} ...",
    )
    _add_common(parser)
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
    _add_common(parser)
    parser.add_argument("commands", nargs="+", choices=[*COMMANDS, "all"], metavar="command")
    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Dispatch to the quick-read parser or the section parser."""
    positional = []
    skip = False
    for arg in argv:  # option values (--host H) are positional-looking: skip them
        if skip:
            skip = False
        elif arg in VALUE_OPTIONS:
            skip = True
        elif not arg.startswith("-"):
            positional.append(arg)
    known = {*COMMANDS, "all"}
    sections = cli_operations()
    # "status" and "sms" are both quick reads and sections: a section command after them wins
    for i, arg in enumerate(positional):
        if arg in sections and i + 1 < len(positional) and positional[i + 1] in sections[arg]:
            return build_parser().parse_args(argv)
        if arg in known:
            return build_read_parser().parse_args(argv)
    return build_parser().parse_args(argv)


def credentials(args: argparse.Namespace) -> tuple[str, str]:
    """Return (username, password) from the environment or the ``--env-file``.

    ``ID525_USERNAME`` / ``ID525_PASSWORD`` win (environment first, then the
    file); a file may also use plain ``USERNAME`` / ``PASSWORD`` keys. Plain
    names are never read from the environment, where ``USERNAME`` is usually
    the system login.
    """
    file_env = load_env_file(args.env_file) if args.env_file else {}
    env = {**file_env, **os.environ}
    username = env.get("ID525_USERNAME") or file_env.get("USERNAME") or DEFAULT_USERNAME
    password = env.get("ID525_PASSWORD") or file_env.get("PASSWORD") or ""
    return username, password


def _client(
    args: argparse.Namespace, *, read_only: bool, tracer: TraceRecorder | None = None
) -> Id525Client:
    username, password = credentials(args)
    return Id525Client(
        args.host, username, password, scheme=args.scheme, read_only=read_only, tracer=tracer
    )


def _require_password(args: argparse.Namespace) -> None:
    """Refuse to log in without a password: a rejected login counts towards the lockout."""
    if not credentials(args)[1]:
        msg = "no password: set ID525_PASSWORD or pass --env-file (nothing was sent)"
        raise Id525AuthenticationError(msg)


async def run(args: argparse.Namespace, tracer: TraceRecorder | None = None) -> Any:
    """Log in once, run the requested command(s), log out."""
    if hasattr(args, "commands"):
        names = list(COMMANDS) if "all" in args.commands else args.commands
        _require_password(args)
        async with _client(args, read_only=True, tracer=tracer) as client:
            return {name: to_jsonable(await COMMANDS[name](client)) for name in names}
    op: Operation = args.operation
    kwargs = {
        name: getattr(args, name)
        for name in inspect.signature(op.function).parameters
        if name != "self"
    }
    if tracer is not None:
        tracer.record("call", operation=op.path, kwargs=to_jsonable(kwargs))
    client = _client(args, read_only=not args.write, tracer=tracer)
    for endpoint in op.endpoints:  # refuse before logging in
        client.check_allowed(endpoint, confirmed=kwargs.get("confirm") is True)
    _require_password(args)
    async with client:
        if any(endpoint.info.kind.mutating for endpoint in op.endpoints):
            await client.get_device_info()  # warns on an untested firmware before writing
        section = getattr(client, op.section or "")  # CLI operations always have a section
        method = getattr(section, op.name)
        result = await method(**kwargs)
    return {"ok": True} if result is None else to_jsonable(result)


def _git_commit() -> str | None:
    """Return the commit of a source checkout of the package (local, no network)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],  # noqa: S607
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    ).stdout.strip()
    return out.stdout.strip() + ("-dirty" if dirty else "")


def _environment() -> dict[str, Any]:
    try:
        version = metadata.version("id525")
    except metadata.PackageNotFoundError:
        version = None
    return {
        "id525": version,
        "commit": _git_commit(),
        "python": platform.python_version(),
        "aiohttp": metadata.version("aiohttp"),
        "platform": platform.platform(),
    }


def default_trace_path(args: argparse.Namespace) -> Path:
    """Return ``$XDG_CACHE_HOME/id525/traces/<timestamp>-<command>.jsonl``."""
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    if hasattr(args, "commands"):
        command = "-".join(args.commands)
    else:
        command = f"{args.section}-{args.command}"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return cache / "id525" / "traces" / f"{stamp}-{command}.jsonl"


class _TraceLogHandler(logging.Handler):
    """Forward the library log (token retries, re-logins...) into the trace."""

    def __init__(self, tracer: TraceRecorder) -> None:
        super().__init__(logging.DEBUG)
        self._tracer = tracer

    def emit(self, record: logging.LogRecord) -> None:
        self._tracer.record(
            "log", level=record.levelname, logger=record.name, message=record.getMessage()
        )


def _error_event(tracer: TraceRecorder, err: BaseException) -> None:
    tracer.record(
        "error",
        type=f"{type(err).__module__}.{type(err).__qualname__}",
        message=str(err),
        attributes={k: repr(v) for k, v in vars(err).items()} if hasattr(err, "__dict__") else {},
        traceback=traceback.format_exception(err),
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
    tracer = TraceRecorder() if args.trace or args.trace_file else None
    with _library_log(verbose=args.verbose, tracer=tracer):
        return _main(args, argv, tracer)


@contextlib.contextmanager
def _library_log(*, verbose: bool, tracer: TraceRecorder | None) -> Iterator[None]:
    """Route the library log to the trace and its warnings (untested firmware) to stderr."""
    library_log = logging.getLogger("id525")
    previous_level = library_log.level
    handlers: list[logging.Handler] = []
    if not verbose:  # with -v, basicConfig already prints everything
        stderr = logging.StreamHandler(sys.stderr)
        stderr.setLevel(logging.WARNING)
        stderr.setFormatter(logging.Formatter("warning: %(message)s"))
        handlers.append(stderr)
    if tracer is not None:
        handlers.append(_TraceLogHandler(tracer))
        library_log.setLevel(logging.DEBUG)
    for handler in handlers:
        library_log.addHandler(handler)
    try:
        yield
    finally:
        for handler in handlers:
            library_log.removeHandler(handler)
        library_log.setLevel(previous_level)


def _main(args: argparse.Namespace, argv: list[str], tracer: TraceRecorder | None) -> int:
    """Run the parsed command and print its result; the trace is written even on errors."""
    try:
        if tracer is not None:
            tracer.record(
                "start",
                argv=argv,
                host=args.host,
                write=getattr(args, "write", False),
                environment=_environment(),
            )
        try:
            result = asyncio.run(run(args, tracer))
        except (Id525Error, NotImplementedError) as err:
            if tracer is not None:
                _error_event(tracer, err)
            hint = " (add --write)" if "read_only=False" in str(err) else ""
            print(f"error: {err}{hint}", file=sys.stderr)  # noqa: T201
            return 1
        except BaseException as err:
            if tracer is not None:
                _error_event(tracer, err)
            raise
        if tracer is not None:
            tracer.record("result", value=result)
        print(json.dumps(result, indent=2, ensure_ascii=False))  # noqa: T201
        return 0
    finally:
        if tracer is not None:
            path = tracer.write(args.trace_file or default_trace_path(args))
            print(f"trace: {path}", file=sys.stderr)  # noqa: T201


if __name__ == "__main__":
    sys.exit(main())
