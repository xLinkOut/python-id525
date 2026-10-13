"""fw-portfwd.html with port-forwarding rules (the real dump has none).

Row keys are the ones the page JS reads; ``protocol`` / ``enable`` /
``externalPortEndRange`` are compared with numbers by the JS (``case 1:``,
``== 0``), so integers are used. ``instance`` being an integer is an assumption.
"""

from __future__ import annotations

import json

from id525.endpoints import Page

from . import Variant, replace_once

RULES = [
    {
        "instance": 3,
        "description": "---",
        "internalClient": "192.168.224.50",
        "externalPort": 8080,
        "externalPortEndRange": 0,
        "internalPort": 80,
        "protocol": 0,
        "enable": 1,
    },
    {
        "instance": 5,
        "description": "---",
        "internalClient": "192.168.224.60",
        "externalPort": 5000,
        "externalPortEndRange": 5010,
        "internalPort": 5000,
        "protocol": 2,
        "enable": 0,
    },
]


def with_rules(html: str) -> str:
    """Inject two rules (one single port, one range) and turn forwarding on."""
    encoded = json.dumps(RULES).replace('"', "&quot;")
    html = replace_once(
        html, 'var port_fwd_entries = "[]";', f'var port_fwd_entries = "{encoded}";'
    )
    return replace_once(html, 'var port_forward_status ="0";', 'var port_forward_status ="1";')


VARIANTS = {
    "fw-portfwd-rules": Variant(Page.PORT_FORWARDING, with_rules, "two port-forwarding rules"),
}
