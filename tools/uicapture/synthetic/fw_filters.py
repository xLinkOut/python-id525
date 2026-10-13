"""Rows for the IP and URL filter pages (both lists are empty in the real dump).

Row shapes follow exactly what the pages' code reads:
- ``fw-ipfilter``: ``ipFilter_entries`` is a JSON list; the page reads
  ``instance``, ``dst_ip``, ``protocol`` and ``ip_type`` of each entry. Numeric
  ``instance`` values are an assumption (as for ``lan-settings`` reservations).
- ``fw-urlfilter``: ``parent_control_profile_get`` is ``"<instance>,<url>;..."``
  with a trailing ``;`` (the page drops the last split item), so instances are
  strings by construction.
Both variants also turn the filter on in whitelist mode, so that "keep the
current value" logic is tested against non-default values.
"""

from __future__ import annotations

import json
import re

from id525.endpoints import Page

from . import Variant, replace_once

IP_RULES = [
    {"instance": 3, "dst_ip": "192.0.2.10", "protocol": "TCP/UDP", "ip_type": "IPv4"},
    {"instance": 8, "dst_ip": "2001:db8::5", "protocol": "TCP/UDP", "ip_type": "IPv6"},
    {"instance": 11, "dst_ip": "198.51.100.7", "protocol": "TCP/UDP", "ip_type": "IPv4"},
]
URL_PROFILE = "3,example.com;5,ads.example.net;9,http://tracker.example.org/x~y#z;"


def ip_filter_rules(html: str) -> str:
    """Three rules (IPv4 + IPv6), filter on, whitelist."""
    entries = json.dumps(IP_RULES, separators=(",", ":")).replace('"', "&quot;")
    html = replace_once(
        html, 'var ipFilter_entries = "[]";', f'var ipFilter_entries = "{entries}";'
    )
    html = replace_once(html, 'var IPFilter_Enable = "0";', 'var IPFilter_Enable = "1";')
    return replace_once(html, 'var pkts_blocklist_mode = "0";', 'var pkts_blocklist_mode = "1";')


def url_filter_rules(html: str) -> str:
    """Three URLs, filter on, whitelist."""
    html, count = re.subn(
        r'var parent_control_profile_get = "[^"]*";',
        f'var parent_control_profile_get = "{URL_PROFILE}";',
        html,
    )
    if count != 1:
        msg = "parent_control_profile_get not found exactly once"
        raise ValueError(msg)
    html = replace_once(
        html,
        'var parent_control_profile_enabled = "0";',
        'var parent_control_profile_enabled = "1";',
    )
    return replace_once(html, 'var isAllow = "0";', 'var isAllow = "1";')


VARIANTS = {
    "fw-ipfilter-rules": Variant(Page.IP_FILTER, ip_filter_rules, ip_filter_rules.__doc__ or ""),
    "fw-urlfilter-rules": Variant(
        Page.URL_FILTER, url_filter_rules, url_filter_rules.__doc__ or ""
    ),
}
