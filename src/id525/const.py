"""Protocol constants for the ID525 web API.

Only read-only endpoints are listed here, on purpose: the client cannot POST to
anything that is not a member of :class:`Endpoint`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DEFAULT_HOST: Final = "192.168.224.1"
DEFAULT_USERNAME: Final = "admin"
DEFAULT_TIMEOUT: Final = 15.0

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


class Endpoint(StrEnum):
    """Allow-listed API endpoints (session handling + reads verified safe)."""

    TOKEN_QUERY = "token_query"
    LOGIN = "login_req"
    LOGOUT = "logout_req"
    LOGIN_QUERY = "login_query"
    NET_STATUS = "net_status_retrieve"
    CLIENT_STATUS = "client_status_retrieve"
    SMS_LIST = "req_smsReload"

    @property
    def path(self) -> str:
        """Return the URL path of the endpoint."""
        return API_PATH.format(self.value)


class Page(StrEnum):
    """Allow-listed UI pages whose HTML embeds read-only data."""

    CELLULAR_STATUS = "cellular-status"
    UTILIZATION = "util-status"
    ABOUT = "help-about"

    @property
    def path(self) -> str:
        """Return the URL path of the page."""
        return PAGE_PATH.format(self.value)
