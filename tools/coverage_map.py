"""Generate the README coverage map from the endpoint registry and the client code.

Usage::

    uv run python -m tools.coverage_map          # rewrite docs/*.svg and the README block
    uv run python -m tools.coverage_map --check  # exit 1 if anything is stale

Everything is derived: statuses come from :mod:`id525.endpoints`, method names
from the ``@uses`` declarations (:mod:`id525.operations`), so the map cannot
drift from the code (``tests/test_coverage_map.py`` enforces it).

Colour (validated with the dataviz palette validator, light and dark):
implemented tiers are one four-step ordinal blue ramp (darker = more trusted on light,
lighter = more trusted on dark); "unsupported by design" is orange; "planned"
is a neutral fill; "dead code" is an outline. Every cell also carries its text
label, and the README table repeats everything, so colour is never the only cue.
"""

from __future__ import annotations

import argparse
import html
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from id525.endpoints import ENDPOINTS, Endpoint, Kind, Page, Status
from id525.operations import operations

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
README = ROOT / "README.md"
START, END = "<!-- coverage:start -->", "<!-- coverage:end -->"

GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Session", ("common",)),
    ("Status", ("net-status", "cellular-status", "client-status", "util-status", "help-about")),
    ("Settings", ("cellular-settings", "lan-settings", "wifi-settings", "voip-settings")),
    (
        "Firewall",
        ("fw-adv", "fw-ddns", "fw-ipfilter", "fw-macfilter", "fw-portfwd", "fw-urlfilter"),
    ),
    ("Admin", ("adm-user", "adm-sms", "adm-sw", "adm-backup")),
    ("Diagnostics", ("self-diag", "self-ping", "self-tracert")),
)

LEGEND: tuple[tuple[str, tuple[Status, ...], str], ...] = (
    (
        "live-verified",
        (Status.LIVE_VERIFIED,),
        "observed on a real router (read-only probes, user traces)",
    ),
    ("ui-captured", (Status.UI_CAPTURED,), "byte-identical to the router UI, captured offline"),
    (
        "ui-captured*",
        (Status.UI_CAPTURED_SYNTHETIC,),
        "as ui-captured, from invented page data (the real dump had no rows)",
    ),
    ("static", (Status.STATIC,), "implemented from the UI code, not captured"),
    ("planned", (Status.PLANNED,), "not implemented yet"),
    (
        "unsupported",
        (Status.STUB_UNSAFE, Status.STUB_POLICY, Status.STUB_UNKNOWN),
        "deliberately not implemented: raises NotImplementedError",
    ),
    ("dead code", (Status.DEAD_CODE,), "never called by the UI"),
    ("no data", (Status.NO_DATA,), "page holds no data beyond what an endpoint returns"),
)

STATUS_ICON = {
    Status.LIVE_VERIFIED: "🟦",
    Status.UI_CAPTURED: "🔵",
    Status.UI_CAPTURED_SYNTHETIC: "🔷",
    Status.STATIC: "🔹",
    Status.PLANNED: "⬜",
    Status.STUB_UNSAFE: "🟧",
    Status.STUB_POLICY: "🟧",
    Status.STUB_UNKNOWN: "🟧",
    Status.DEAD_CODE: "▫️",
    Status.NO_DATA: "◽",
}


@dataclass(frozen=True)
class Theme:
    """Colours of one mode (dataviz reference palette)."""

    name: str
    surface: str
    ink: str
    ink_secondary: str
    muted: str
    hairline: str
    fills: dict[str, str]
    """Legend label -> fill ("" = outline only)."""


LIGHT = Theme(
    name="light",
    surface="#fcfcfb",
    ink="#0b0b0b",
    ink_secondary="#52514e",
    muted="#898781",
    hairline="#c3c2b7",
    fills={
        "live-verified": "#184f95",
        "ui-captured": "#2a78d6",
        "ui-captured*": "#5598e7",
        "static": "#86b6ef",
        "planned": "#f0efec",
        "unsupported": "#eb6834",
        "dead code": "",
        "no data": "",
    },
)
DARK = Theme(
    name="dark",
    surface="#1a1a19",
    ink="#f0efec",
    ink_secondary="#c3c2b7",
    muted="#898781",
    hairline="#383835",
    fills={
        "live-verified": "#b7d3f6",
        "ui-captured": "#6da7ec",
        "ui-captured*": "#3987e5",
        "static": "#1c5cab",
        "planned": "#2c2c2a",
        "unsupported": "#d95926",
        "dead code": "",
        "no data": "",
    },
)

FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, monospace"
LABEL_W = 210
CELL_W, CELL_H, GAP = 160, 44, 4
PER_ROW = 6
PAD = 24
WIDTH = PAD + LABEL_W + PER_ROW * (CELL_W + GAP) - GAP + PAD


@dataclass(frozen=True)
class Cell:
    """One square of the map: a page read or an endpoint."""

    title: str
    detail: str
    status: Status
    kind: Kind
    method: str | None


def legend_label(status: Status) -> str:
    """Return the legend entry a status belongs to."""
    return next(label for label, statuses, _ in LEGEND if status in statuses)


def methods_by_target() -> dict[Endpoint | Page, list[str]]:
    """Map each endpoint / page to the client methods that use it."""
    found: dict[Endpoint | Page, list[str]] = {}
    for op in operations():
        for target in op.targets:
            found.setdefault(target, []).append(op.path)
    return found


def rows() -> list[tuple[str, str, list[Cell]]]:
    """Return ``(group, page label, cells)`` per UI page, in display order."""
    methods = methods_by_target()
    out = []
    for group, pages in GROUPS:
        for page_name in pages:
            cells = []
            if page_name == "common":
                label = "Session (shared UI script)"
            else:
                page = Page(page_name)
                label = page.info.title
                cells.append(
                    Cell(
                        "Page data",
                        f"{page_name}.html",
                        page.info.status,
                        Kind.READ,
                        next(iter(methods.get(page, [])), None),
                    )
                )
            for endpoint, info in ENDPOINTS.items():
                if info.page == page_name:
                    cells.append(
                        Cell(
                            info.summary,
                            endpoint.value,
                            info.status,
                            info.kind,
                            next(
                                (m for m in methods.get(endpoint, []) if not m.startswith("_")),
                                None,
                            ),
                        )
                    )
            out.append((group, label, cells))
    return out


def all_cells() -> list[Cell]:
    """Return every cell of the map."""
    return [cell for _, _, cells in rows() for cell in cells]


def _luminance(hex_color: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_on(fill: str, theme: Theme) -> str:
    """Pick the ink (dark or light) with the best contrast on a fill."""
    if not fill:
        return theme.ink_secondary
    return max(("#0b0b0b", "#ffffff"), key=lambda ink: _contrast(fill, ink))


def outline(label: str, theme: Theme) -> str:
    """Stroke of a legend entry: outline-only entries differ by dash pattern."""
    if label == "dead code":
        return f'stroke="{theme.hairline}" stroke-width="1.5" stroke-dasharray="4 3"'
    if label == "no data":
        return f'stroke="{theme.hairline}" stroke-width="1.5" stroke-dasharray="1 3"'
    if label == "planned":
        return f'stroke="{theme.hairline}" stroke-width="1"'
    return ""


def _fit(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def svg(theme: Theme) -> str:
    """Render the map for one theme."""
    cells = all_cells()
    total = len(cells)
    counts = Counter(legend_label(c.status) for c in cells)
    implemented = sum(1 for c in cells if c.status.implemented)
    parts: list[str] = []
    y = PAD

    def text(
        x: float,
        y: float,
        value: str,
        *,
        size: int,
        fill: str,
        weight: int = 400,
        mono: bool = False,
    ) -> None:
        family = MONO if mono else FONT
        parts.append(
            f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}">{html.escape(value)}</text>'
        )

    text(PAD, y + 18, "ID525 web API coverage", size=20, fill=theme.ink, weight=600)
    text(
        PAD,
        y + 40,
        f"{implemented} of {total} UI features implemented · every square is one page or "
        "API endpoint of the router web UI",
        size=13,
        fill=theme.ink_secondary,
    )
    y += 64
    x: float = PAD
    for label, _, _ in LEGEND:
        fill = theme.fills[label]
        stroke = outline(label, theme)
        parts.append(
            f'<rect x="{x}" y="{y}" width="14" height="14" rx="3" '
            f'fill="{fill or "none"}" {stroke}/>'
        )
        entry = f"{label} {counts.get(label, 0)}"
        text(x + 20, y + 11.5, entry, size=12, fill=theme.ink_secondary)
        x += 20 + len(entry) * 6.5 + 24
    y += 34

    current_group = None
    for group, label, row_cells in rows():
        if group != current_group:
            current_group = group
            y += 8
            text(PAD, y + 12, group.upper(), size=11, fill=theme.muted, weight=600)
            parts.append(
                f'<line x1="{PAD + 90}" y1="{y + 8}" x2="{WIDTH - PAD}" y2="{y + 8}" '
                f'stroke="{theme.hairline}" stroke-width="1"/>'
            )
            y += 22
        text(PAD, y + CELL_H / 2 + 4, _fit(label, 28), size=13, fill=theme.ink, weight=500)
        for i, cell in enumerate(row_cells):
            if i and i % PER_ROW == 0:
                y += CELL_H + GAP
            cx = PAD + LABEL_W + (i % PER_ROW) * (CELL_W + GAP)
            fill = theme.fills[legend_label(cell.status)]
            stroke = outline(legend_label(cell.status), theme)
            tooltip = f"{cell.title} ({cell.detail}): {cell.status}, {cell.kind}" + (
                f" → client.{cell.method}" if cell.method else ""
            )
            parts.append(
                f'<g><title>{html.escape(tooltip)}</title><rect x="{cx}" y="{y}" '
                f'width="{CELL_W}" height="{CELL_H}" rx="4" fill="{fill or "none"}" {stroke}/>'
            )
            ink = text_on(fill, theme)
            text(cx + 8, y + 18, _fit(cell.title, 22), size=12, fill=ink, weight=500)
            text(cx + 8, y + 34, _fit(cell.detail, 25), size=10, fill=ink, mono=True)
            parts.append("</g>")
        y += CELL_H + GAP
    height = y + PAD
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" '
        f'aria-label="ID525 API coverage: {implemented} of {total} features implemented">'
        f'<rect width="{WIDTH}" height="{height}" rx="8" fill="{theme.surface}"/>'
        + "".join(parts)
        + "</svg>\n"
    )


# absolute, so the picture also shows on PyPI (which can't resolve repository paths)
IMAGE_BASE = "https://raw.githubusercontent.com/xLinkOut/python-id525/main/docs"


def markdown() -> str:
    """Render the README block: the picture, a summary and the full table."""
    cells = all_cells()
    counts = Counter(legend_label(c.status) for c in cells)
    lines = [
        START,
        "<!-- generated by `uv run python -m tools.coverage_map`; do not edit by hand -->",
        "<picture>",
        f'  <source media="(prefers-color-scheme: dark)" srcset="{IMAGE_BASE}/coverage-dark.svg">',
        f'  <img alt="Coverage map of the ID525 web API" src="{IMAGE_BASE}/coverage-light.svg">',
        "</picture>",
        "",
        "| Status | Meaning | Count |",
        "|---|---|---:|",
    ]
    for label, statuses, meaning in LEGEND:
        icon = STATUS_ICON[statuses[0]]
        lines.append(f"| {icon} {label} | {meaning} | {counts.get(label, 0)} |")
    lines += [
        "",
        "<details><summary>Every page and endpoint</summary>",
        "",
        "| Page | Feature | Endpoint | Kind | Status | Client |",
        "|---|---|---|---|---|---|",
    ]
    for _, label, row_cells in rows():
        for cell in row_cells:
            method = f"`{cell.method}()`" if cell.method else ""
            lines.append(
                f"| {label} | {cell.title} | `{cell.detail}` | {cell.kind} | "
                f"{STATUS_ICON[cell.status]} {cell.status} | {method} |"
            )
    lines += ["", "</details>", END]
    return "\n".join(lines)


def outputs() -> dict[Path, str]:
    """Return every generated file and its content."""
    readme = README.read_text()
    if START not in readme or END not in readme:
        msg = f"README is missing the {START} / {END} markers"
        raise SystemExit(msg)
    head, rest = readme.split(START, 1)
    _, tail = rest.split(END, 1)
    return {
        DOCS / "coverage-light.svg": svg(LIGHT),
        DOCS / "coverage-dark.svg": svg(DARK),
        README: head + markdown() + tail,
    }


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if outputs are stale")
    args = parser.parse_args(argv)
    stale = [p for p, content in outputs().items() if not p.exists() or p.read_text() != content]
    if args.check:
        for path in stale:
            print(f"stale: {path.relative_to(ROOT)}")
        return 1 if stale else 0
    DOCS.mkdir(exist_ok=True)
    for path, content in outputs().items():
        path.write_text(content)
    print(f"wrote {len(outputs())} files ({len(stale)} changed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
