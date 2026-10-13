"""fw-macfilter.html with MAC filter rules (the real dump has none: ``tmp = "[]"``).

Row keys are the ones the page JS reads (``instance``, ``description``,
``macAddress``); the integer ``instance`` type is an assumption. Rule 6
uses connected client host-04's MAC in upper case (duplicate checks are
case-insensitive).
"""

from __future__ import annotations

import json

from id525.endpoints import Page

from . import Variant, replace_once

RULES = [
    {"instance": 2, "description": "tablet", "macAddress": "02:00:5E:00:01:0A"},
    {"instance": 6, "description": "console-1", "macAddress": "02:00:5E:00:00:06"},
]


def with_rules(html: str) -> str:
    """Inject two rules into the page's ``tmp`` variable (entity-encoded JSON)."""
    encoded = json.dumps(RULES).replace('"', "&quot;")
    return replace_once(html, 'var tmp = "[]";', f'var tmp = "{encoded}";')


VARIANTS = {
    "fw-macfilter-rules": Variant(Page.MAC_FILTER, with_rules, "two MAC filter rules"),
}
