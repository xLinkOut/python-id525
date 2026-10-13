"""Synthetic page variants: real anonymised fixtures plus invented table rows.

The real dump has empty tables on several pages (port forwards, IP / MAC / URL
filters...), so edit and delete flows have nothing to act on. Each module in
this package exposes ``VARIANTS: dict[str, Variant]``; ``python -m
tools.uicapture.synthetic`` writes them to ``tests/fixtures/synthetic/``.

Invented rows follow the shape the page's own JS reads, but the types of real
entries are an assumption: scenarios using a variant must set ``synthetic=True``.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from id525.endpoints import Page

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures"
OUT = FIXTURES / "synthetic"


@dataclass(frozen=True)
class Variant:
    """A page fixture transformed by ``build`` (receives and returns the HTML)."""

    page: Page
    build: Callable[[str], str]
    description: str


def variants() -> dict[str, Variant]:
    """Collect ``VARIANTS`` from every module of this package."""
    found: dict[str, Variant] = {}
    for module in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if module.name == "__main__":
            continue
        for name, variant in importlib.import_module(f"{__name__}.{module.name}").VARIANTS.items():
            if name in found:
                msg = f"duplicate synthetic variant {name}"
                raise ValueError(msg)
            found[name] = variant
    return found


def render(variant: Variant) -> str:
    """Build a variant from its base fixture."""
    return variant.build((FIXTURES / f"{variant.page}.html").read_text())


def replace_once(html: str, old: str, new: str) -> str:
    """Replace exactly one occurrence (fail loudly if the page changed)."""
    if html.count(old) != 1:
        msg = f"expected exactly one {old!r} in the page, found {html.count(old)}"
        raise ValueError(msg)
    return html.replace(old, new)


def main() -> int:
    """Write every variant to ``tests/fixtures/synthetic``."""
    OUT.mkdir(exist_ok=True)
    for name, variant in variants().items():
        (OUT / f"{name}.html").write_text(render(variant))
        print(f"{name}: {variant.description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
