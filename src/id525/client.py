"""Async client for the General Mobile ID525 web API.

Protocol summary (verified against firmware ``ID525_REL_1.0.09.17``):

* Every API call is ``POST /cgi-bin/cgi/<name>.cgi`` with a JSON body.
* A CSRF token (``RequestVerifyToken``) must be sent in the body. Tokens are
  single-use and strictly sequential: every response carries the next one,
  even error responses. All calls are therefore serialised with a lock.
* The router allows a single admin session: logging in kicks out any other
  admin session (e.g. the web UI), and vice versa.
* Repeated login failures make the router refuse logins for a while, so this
  client never retries a rejected login on its own.

The client is **read-only by design**: it can only reach the endpoints and
pages allow-listed in :mod:`id525.const`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Literal, Self

import aiohttp

from .const import (
    DEFAULT_HOST,
    DEFAULT_TIMEOUT,
    DEFAULT_USERNAME,
    EMPTY_BODY,
    ERROR_INVALID_TOKEN,
    ERROR_LOGIN_REFUSED,
    ERROR_TOKEN_NOT_INIT,
    SESSION_COOKIE,
    TOKEN_FIELD,
    Endpoint,
    Page,
)
from .exceptions import (
    Id525AuthenticationError,
    Id525ConnectionError,
    Id525Error,
    Id525LoginLockedError,
    Id525ResponseError,
    Id525SessionExpiredError,
    Id525SessionKickedError,
)
from .models import LoginState
from .parsers import (
    is_redirect_page,
    parse_about_page,
    parse_cellular_page,
    parse_clients,
    parse_int,
    parse_network_status,
    parse_sms,
    parse_utilization_page,
)

if TYPE_CHECKING:
    import ssl
    from types import TracebackType

    from .models import (
        CellularInfo,
        ConnectedClient,
        DeviceInfo,
        NetworkStatus,
        SmsInbox,
        Utilization,
    )

_LOGGER = logging.getLogger(__name__)

_MAX_TOKEN_NOT_INIT_RETRIES = 2


class _NotAuthenticatedError(Exception):
    """Internal: the router answered as if no session existed."""


class _InvalidTokenError(Exception):
    """Internal: the CSRF token was rejected (a fresh one has been stored)."""


class Id525Client:
    """Read-only async client for one ID525 router.

    Use as an async context manager, or call :meth:`login` / :meth:`close`.
    If you pass your own ``aiohttp.ClientSession``, give it an
    ``aiohttp.DummyCookieJar()``: the client manages the session cookie itself.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        username: str = DEFAULT_USERNAME,
        password: str = "",
        *,
        session: aiohttp.ClientSession | None = None,
        ssl_context: ssl.SSLContext | aiohttp.Fingerprint | Literal[False] = False,
        scheme: Literal["https", "http"] = "https",
        request_timeout: float = DEFAULT_TIMEOUT,
        auto_relogin: bool = True,
    ) -> None:
        """Initialise the client.

        Args:
            host: router host, optionally with ``:port``.
            username: admin username.
            password: admin password.
            session: optional shared aiohttp session.
            ssl_context: TLS verification. The router uses a self-signed
                certificate, so the default is ``False`` (no verification);
                pass an ``aiohttp.Fingerprint`` to pin the certificate.
            scheme: URL scheme (the router only serves HTTPS; ``http`` is for tests).
            request_timeout: per-request timeout in seconds.
            auto_relogin: transparently log in again when the session expired.
                Never applies after being kicked by another admin login, nor
                after a rejected login.

        """
        self._base_url = f"{scheme}://{host}"
        self._username = username
        self._password = password
        self._session = session
        self._owns_session = session is None
        self._ssl = ssl_context
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)
        self._auto_relogin = auto_relogin
        self._lock = asyncio.Lock()
        self._session_id: str | None = None
        self._token: str | None = None
        self._logged_in = False
        self._auth_failed = False

    async def __aenter__(self) -> Self:
        await self.login()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    @property
    def host(self) -> str:
        """Return the router base URL."""
        return self._base_url

    @property
    def is_logged_in(self) -> bool:
        """Return True if the client believes it holds a valid session."""
        return self._logged_in

    async def close(self) -> None:
        """Log out (best effort) and release the HTTP session if owned."""
        try:
            if self._logged_in:
                await self.logout()
        except Id525Error as err:
            _LOGGER.debug("Logout during close failed: %s", err)
        finally:
            if self._owns_session and self._session is not None:
                await self._session.close()
                self._session = None

    async def login(self) -> None:
        """Log in, taking over the router's single admin session.

        Raises:
            Id525AuthenticationError: wrong credentials (never retried).
            Id525LoginLockedError: the router is refusing logins for a while.
            Id525ConnectionError: the router is unreachable.

        """
        async with self._lock:
            self._auth_failed = False  # an explicit login is a deliberate retry
            await self._login_locked()

    async def logout(self) -> None:
        """Log out, freeing the admin session for the web UI."""
        async with self._lock:
            try:
                if self._session_id is not None:
                    await self._post(Endpoint.LOGOUT, EMPTY_BODY, check=True)
            except _NotAuthenticatedError:
                _LOGGER.debug("Session was already gone at logout")
            finally:
                self._logged_in = False
                self._session_id = None
                self._token = None

    async def get_login_state(self) -> LoginState:
        """Return the router's view of the current session (no login attempted)."""
        async with self._lock:
            return await self._login_state_locked()

    async def ensure_session(self) -> LoginState:
        """Validate the session before a batch of reads; log in if needed.

        Call this at the start of every polling cycle. The router reports that
        a session was taken over (``KICKED``) only once, to the *first* request
        made with the old session; any other call would consume that notice and
        make a kick indistinguishable from an expiry (verified live).

        Raises:
            Id525SessionKickedError: another admin login took over the session.
            Id525SessionExpiredError: the session ended and auto re-login is off.

        """
        async with self._lock:
            if not self._logged_in:
                await self._login_locked()
                return LoginState.LOGGED_IN
            state = await self._login_state_locked()
            if state is LoginState.EXPIRING:
                await self._post(Endpoint.TOKEN_QUERY, EMPTY_BODY)  # the UI's "Extend"
            if state in (LoginState.LOGGED_IN, LoginState.EXPIRING):
                return state
            self._logged_in = False
            if state is LoginState.KICKED:
                msg = "another admin login took over the router session"
                raise Id525SessionKickedError(msg)
            if not self._auto_relogin:
                msg = f"router session ended (state={state.name})"
                raise Id525SessionExpiredError(msg)
            _LOGGER.debug("Session not valid (state=%s), logging in again", state.name)
            await self._login_locked()
            return LoginState.LOGGED_IN

    async def keep_alive(self) -> None:
        """Refresh the CSRF token; the web UI uses this call to extend the session."""
        await self._call(Endpoint.TOKEN_QUERY, with_token=False)

    async def _login_locked(self) -> None:
        if self._auth_failed:
            msg = "a previous login was rejected; call login() explicitly to retry"
            raise Id525AuthenticationError(msg)
        self._logged_in = False
        self._session_id = None
        self._token = None
        _, session_id = await self._get_text("/")  # get a session cookie, like a browser
        if session_id:
            self._session_id = session_id
        await self._post(Endpoint.TOKEN_QUERY, EMPTY_BODY)
        for _ in range(_MAX_TOKEN_NOT_INIT_RETRIES + 1):
            data = await self._post(
                Endpoint.LOGIN,
                {TOKEN_FIELD: self._token, "usr": self._username, "pwd": self._password},
            )
            if data.get("result") is True:
                self._logged_in = True
                _LOGGER.debug("Logged in to %s", self._base_url)
                return
            error = data.get("error")
            if error == ERROR_TOKEN_NOT_INIT:
                await asyncio.sleep(1)  # mimic the web UI before retrying
                continue
            self._auth_failed = True
            if error == ERROR_LOGIN_REFUSED:
                raise Id525LoginLockedError(parse_int(data.get("lock_time")))
            msg = f"login rejected by router: {error!r}"
            raise Id525AuthenticationError(msg)
        msg = "router never initialised the login token"
        raise Id525ResponseError(msg)

    async def _login_state_locked(self) -> LoginState:
        data = await self._post(Endpoint.LOGIN_QUERY, EMPTY_BODY)
        value = parse_int(data.get("login"))
        return LoginState(value if value is not None else LoginState.UNKNOWN)

    async def _recover_session_locked(self) -> None:
        """Handle a "not authenticated" answer: re-login or raise."""
        was_logged_in = self._logged_in
        self._logged_in = False
        state = await self._login_state_locked() if was_logged_in else LoginState.NOT_LOGGED_IN
        if state is LoginState.KICKED:
            msg = "another admin login took over the router session"
            raise Id525SessionKickedError(msg)
        if was_logged_in and not self._auto_relogin:
            msg = f"router session ended (state={state.name})"
            raise Id525SessionExpiredError(msg)
        _LOGGER.debug("Session not valid (state=%s), logging in again", state.name)
        await self._login_locked()

    async def get_network_status(self) -> NetworkStatus:
        """Return the main status dashboard (SIM, signal, WAN, data usage, Wi-Fi)."""
        return parse_network_status(await self._call(Endpoint.NET_STATUS))

    async def get_clients(self) -> tuple[ConnectedClient, ...]:
        """Return the LAN client list."""
        return parse_clients(await self._call(Endpoint.CLIENT_STATUS))

    async def get_sms(self) -> SmsInbox:
        """Return the SMS store. Read-only: messages are never marked as read."""
        return parse_sms(await self._call(Endpoint.SMS_LIST))

    async def get_cellular_info(self) -> CellularInfo:
        """Return serving-cell radio details (RSRP/RSRQ/SNR, band, PCI...)."""
        return parse_cellular_page(await self._page(Page.CELLULAR_STATUS))

    async def get_utilization(self) -> Utilization:
        """Return CPU / memory / throughput statistics and uptime."""
        return parse_utilization_page(await self._page(Page.UTILIZATION))

    async def get_device_info(self) -> DeviceInfo:
        """Return model, versions and identifiers (IMEI, IMSI, ...)."""
        return parse_about_page(await self._page(Page.ABOUT))

    async def _call(self, endpoint: Endpoint, *, with_token: bool = True) -> dict[str, Any]:
        """Call an allow-listed endpoint with session and token recovery."""
        async with self._lock:
            if not self._logged_in:
                await self._login_locked()
            recovered = False
            for attempt in range(3):
                if with_token and self._token is None:
                    await self._post(Endpoint.TOKEN_QUERY, EMPTY_BODY)
                body: object = {TOKEN_FIELD: self._token} if with_token else EMPTY_BODY
                try:
                    return await self._post(endpoint, body, check=True)
                except _InvalidTokenError:
                    _LOGGER.debug("Token rejected by %s (attempt %d)", endpoint, attempt + 1)
                except _NotAuthenticatedError:
                    if recovered:
                        msg = "router rejected the session right after login"
                        raise Id525SessionExpiredError(msg) from None
                    await self._recover_session_locked()
                    recovered = True
            msg = f"router kept rejecting the CSRF token for {endpoint}"
            raise Id525ResponseError(msg)

    async def _page(self, page: Page) -> str:
        """GET an allow-listed UI page with session recovery."""
        async with self._lock:
            if not self._logged_in:
                await self._login_locked()
            for attempt in range(2):
                html, session_id = await self._get_text(page.path)
                # Serving a page makes the router issue a new CSRF token (embedded
                # in the page, if at all): the one we hold is now invalid.
                self._token = None
                if not is_redirect_page(html):
                    if session_id:
                        self._session_id = session_id
                    return html
                if attempt:
                    break
                await self._recover_session_locked()
            msg = f"router kept redirecting {page.path} to the login page"
            raise Id525SessionExpiredError(msg)

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())
            self._owns_session = True
        return self._session

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(extra or {})
        if self._session_id:
            headers["Cookie"] = f"{SESSION_COOKIE}={self._session_id}"
        return headers

    @staticmethod
    def _session_cookie(response: aiohttp.ClientResponse) -> str | None:
        """Return the session id set by a response, if any.

        Callers adopt it only from *authenticated* answers: unauthenticated ones
        hand out a fresh anonymous session, and adopting it would hide the fact
        that our session was kicked (only the old session id reports KICKED).
        """
        cookie = response.cookies.get(SESSION_COOKIE)
        return cookie.value if cookie is not None and cookie.value else None

    async def _get_text(self, path: str) -> tuple[str, str | None]:
        try:
            async with self._http().get(
                self._base_url + path,
                headers=self._headers(),
                ssl=self._ssl,
                timeout=self._timeout,
                allow_redirects=False,
            ) as resp:
                resp.raise_for_status()
                raw = await resp.read()
                session_id = self._session_cookie(resp)
        except (aiohttp.ClientError, TimeoutError) as err:
            msg = f"GET {path} failed: {err}"
            raise Id525ConnectionError(msg) from err
        return raw.decode("utf-8", errors="replace"), session_id

    async def _post(
        self, endpoint: Endpoint, body: object, *, check: bool = False
    ) -> dict[str, Any]:
        """POST to an endpoint, rotate the token, detect session/token errors."""
        if not isinstance(endpoint, Endpoint):  # defence in depth: allow-list only
            msg = f"endpoint {endpoint!r} is not allow-listed"
            raise TypeError(msg)
        try:
            async with self._http().post(
                self._base_url + endpoint.path,
                data=json.dumps(body),
                headers=self._headers({"Content-Type": "application/json"}),
                ssl=self._ssl,
                timeout=self._timeout,
                allow_redirects=False,
            ) as resp:
                resp.raise_for_status()
                text = await resp.text(errors="replace")
                session_id = self._session_cookie(resp)
        except (aiohttp.ClientError, TimeoutError) as err:
            msg = f"POST {endpoint.path} failed: {err}"
            raise Id525ConnectionError(msg) from err

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Unauthenticated calls get a broken CGI answer (a leaked header).
            if check:
                raise _NotAuthenticatedError from None
            msg = f"non-JSON answer from {endpoint.path}"
            raise Id525ResponseError(msg) from None
        if not isinstance(data, dict):
            msg = f"unexpected JSON payload from {endpoint.path}"
            raise Id525ResponseError(msg)
        if session_id:
            self._session_id = session_id

        token = data.get(TOKEN_FIELD)
        fresh_token = isinstance(token, str) and bool(token)
        if fresh_token:
            self._token = token
        if check and data.get("result") is False and data.get("error") == ERROR_INVALID_TOKEN:
            if not fresh_token:  # e.g. req_smsReload: force a token_query on retry
                self._token = None
            raise _InvalidTokenError
        return data
