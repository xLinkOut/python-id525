"""The README coverage map must match the code (regenerate with tools.coverage_map)."""

from __future__ import annotations

import re

from tools import coverage_map


def test_coverage_map_is_up_to_date() -> None:
    stale = [
        str(path.relative_to(coverage_map.ROOT))
        for path, content in coverage_map.outputs().items()
        if not path.exists() or path.read_text() != content
    ]
    assert stale == [], "run: uv run python -m tools.coverage_map"


def test_map_has_one_cell_per_page_and_endpoint() -> None:
    from id525.endpoints import Endpoint, Page

    assert len(coverage_map.all_cells()) == len(Endpoint) + len(Page)


def test_svg_is_static() -> None:
    """GitHub serves README images through a sanitiser: no scripts, links or styles."""
    for theme in (coverage_map.LIGHT, coverage_map.DARK):
        svg = coverage_map.svg(theme)
        assert not re.search(r"<script|<style|href=|<foreignObject|on\w+=", svg)
