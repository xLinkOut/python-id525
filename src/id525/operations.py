"""Introspection of the public API: every operation and what it calls.

Built from the :func:`id525.endpoints.uses` declarations, so it can never drift
from the code. Used by the CLI, the coverage map and the tests.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .client import Id525Client
from .endpoints import Endpoint, Kind, Page
from .sections import SECTIONS

if TYPE_CHECKING:
    from collections.abc import Callable

_KIND_ORDER = (Kind.SESSION, Kind.READ, Kind.ACTION, Kind.WRITE, Kind.DESTRUCTIVE)


@dataclass(frozen=True, slots=True)
class Operation:
    """A public client coroutine and the endpoints / pages it touches."""

    section: str | None
    """Client attribute holding it (``None`` for methods of the client itself)."""
    name: str
    function: Callable[..., object]
    targets: tuple[Endpoint | Page, ...]

    @property
    def path(self) -> str:
        """Return the dotted path from the client, e.g. ``lan.add_dhcp_reservation``."""
        return f"{self.section}.{self.name}" if self.section else self.name

    @property
    def endpoints(self) -> tuple[Endpoint, ...]:
        """Return the API endpoints among the targets."""
        return tuple(t for t in self.targets if isinstance(t, Endpoint))

    @property
    def kind(self) -> Kind:
        """Return the most dangerous kind among the targets (pages are reads)."""
        kinds = [e.info.kind for e in self.endpoints] or [Kind.READ]
        return max(kinds, key=_KIND_ORDER.index)

    @property
    def implemented(self) -> bool:
        """Return False for stubs that always raise ``NotImplementedError``."""
        return all(e.info.status.implemented for e in self.endpoints)


def _collect(section: str | None, cls: type) -> list[Operation]:
    found = []
    for name, member in inspect.getmembers(cls, inspect.iscoroutinefunction):
        targets = getattr(member, "__id525_uses__", None)
        if targets is not None and not name.startswith("_"):
            found.append(Operation(section, name, member, targets))
    return found


def operations() -> list[Operation]:
    """Return every public operation, client methods first, then sections."""
    ops = _collect(None, Id525Client)
    for section, cls in SECTIONS.items():
        ops += _collect(section, cls)
    return ops
