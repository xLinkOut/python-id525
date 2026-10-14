"""Protocol constants for the ID525 web API.

The endpoint / page allow-list lives in :mod:`id525.endpoints`.
"""

from __future__ import annotations

from typing import Final

DEFAULT_HOST: Final = "192.168.224.1"
DEFAULT_USERNAME: Final = "admin"
DEFAULT_TIMEOUT: Final = 15.0

# Firmware every fixture, UI capture and live finding comes from. Another
# firmware may change pages, request bodies or answers: the client warns.
TESTED_FIRMWARE: Final = frozenset({"ID525_REL_1.0.09.17"})

SESSION_COOKIE: Final = "QSESSIONID"
TOKEN_FIELD: Final = "RequestVerifyToken"

API_PATH: Final = "/cgi-bin/cgi/{}.cgi"
PAGE_PATH: Final = "/cgi-bin/cm/{}.html"

# The web UI calls JSON.stringify('{}') for parameterless calls, so the body on
# the wire is the 4-byte JSON *string* literal "{}". Serialising this Python
# string with json.dumps reproduces it exactly.
EMPTY_BODY: Final = "{}"

ERROR_INVALID_TOKEN: Final = "Invalid token."
ERROR_TOKEN_NOT_INIT: Final = "Token not init."
ERROR_LOGIN_REFUSED: Final = "Refuse login"

# Markers of the tiny HTML page served instead of the requested one when the
# session is not authenticated.
REDIRECT_PAGE_MARKERS: Final = ('id="redirect_body"', "redirect_top(")
