"""cellular-settings: the real dump has one user APN; fill all four user slots."""

from __future__ import annotations

import json

from id525.endpoints import Page

from . import Variant, replace_once

# Shape copied from the real user1ApnInfo entry; values invented. Some values
# are URI-encoded, as the UI decodes name/apn/user/passwd with decodeURIComponent.
_USER_APNS = {
    "user2ApnInfo": {
        "active": 0,
        "profile_handle": 3,
        "instance": 3,
        "name": "ims%20profile",
        "apn": "ims",
        "IPType": 1,
        "auth": "PAP",
        "user": "user%40example",
        "passwd": "p%26ss",
        "disable": 1,
    },
    "user3ApnInfo": {
        "active": 0,
        "profile_handle": 4,
        "instance": 5,
        "name": "mms",
        "apn": "mms.example.it",
        "IPType": 0,
        "auth": "CHAP",
        "user": "mms",
        "passwd": "secret",
        "disable": 0,
    },
    "user4ApnInfo": {
        "active": 0,
        "profile_handle": 5,
        "instance": 8,
        "name": "iot",
        "apn": "iot.example",
        "IPType": 2,
        "auth": "NONE",
        "user": "",
        "passwd": "",
        "disable": 0,
    },
}


def five_apns(html: str) -> str:
    """Fill user APN slots 2-4 (5 profiles: the UI's maximum)."""
    for var, entry in _USER_APNS.items():
        encoded = json.dumps(entry, separators=(",", ":")).replace('"', "&quot;")
        html = replace_once(html, f"var {var} = '{{}}';", f"var {var} = '{encoded}';")
    return html


VARIANTS = {
    "cellular-settings-5-apns": Variant(
        Page.CELLULAR_SETTINGS, five_apns, "five APN profiles (non-contiguous instances)"
    ),
}
