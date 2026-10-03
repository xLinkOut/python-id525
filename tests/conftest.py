"""Test fixtures: an in-process fake ID525 router.

The fake reproduces the protocol behaviour verified on the real device:
single-use rotating CSRF tokens, a single admin session (a new login kicks the
previous one), non-JSON answers for unauthenticated API calls, a redirect page
for unauthenticated page GETs, and login lockout.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from id525 import Id525Client

FIXTURES = Path(__file__).parent / "fixtures"
USERNAME = "admin"
PASSWORD = "correct-horse"
REDIRECT_PAGE = (
    "<!DOCTYPE HTML PUBLIC '-//W3C//DTD HTML 3.2//EN'><html><head><title></title>"
    '<script type="text/javascript" src="/js/common.js"></script><script>function '
    'topReturn() { redirect_top("/") }</script></head><body id="redirect_body"></body></html>'
)


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


@dataclass
class FakeSession:
    sid: str
    token: str | None = None
    logged_in: bool = False
    state: int = 0  # login_query value


@dataclass
class FakeRouter:
    """State + request log of the fake router."""

    sessions: dict[str, FakeSession] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    bodies: list[tuple[str, bytes]] = field(default_factory=list)
    failed_logins: int = 0
    lock_after: int = 3
    token_not_init: int = 0  # how many login attempts answer "Token not init."

    def admin(self) -> FakeSession | None:
        return next((s for s in self.sessions.values() if s.logged_in), None)

    def expire_all(self) -> None:
        for s in self.sessions.values():
            if s.logged_in:
                s.logged_in, s.state = False, 2

    def kick_all(self) -> None:
        for s in self.sessions.values():
            if s.logged_in:
                s.logged_in, s.state = False, 3

    def invalidate_tokens(self) -> None:
        for s in self.sessions.values():
            s.token = "stale"

    def count(self, name: str) -> int:
        return self.calls.count(name)

    def _session(self, request: web.Request) -> FakeSession | None:
        sid = request.cookies.get("QSESSIONID")
        return self.sessions.get(sid) if sid else None

    def _new_session(self) -> FakeSession:
        session = FakeSession(sid=secrets.token_hex(16))
        self.sessions[session.sid] = session
        return session

    @staticmethod
    def _rotate(session: FakeSession) -> str:
        session.token = secrets.token_urlsafe(48)
        return session.token

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.root)
        app.router.add_get("/cgi-bin/cm/{page}.html", self.page)
        app.router.add_post("/cgi-bin/cgi/{name}.cgi", self.api)
        return app

    async def root(self, request: web.Request) -> web.Response:
        self.calls.append("GET /")
        resp = web.Response(text="<html>root</html>", content_type="text/html")
        if self._session(request) is None:
            resp.set_cookie("QSESSIONID", self._new_session().sid)
        return resp

    async def page(self, request: web.Request) -> web.Response:
        name = request.match_info["page"]
        self.calls.append(f"page:{name}")
        session = self._session(request)
        if session is not None and session.state in (2, 3):
            session.state = 0
        if session is None or not session.logged_in:
            # the real router also hands out a fresh anonymous session here
            resp = web.Response(text=REDIRECT_PAGE, content_type="text/html")
            resp.set_cookie("QSESSIONID", self._new_session().sid)
            return resp
        self._rotate(session)  # the real router invalidates the token on page loads
        return web.Response(text=load_fixture(f"{name}.html"), content_type="text/html")

    async def api(self, request: web.Request) -> web.Response:
        name = request.match_info["name"]
        raw = await request.read()
        self.calls.append(name)
        self.bodies.append((name, raw))
        body: Any = json.loads(raw) if raw else None
        session = self._session(request)
        if session is None:
            return web.json_response({"result": False, "error": "no session"})
        if session.state in (2, 3):
            # Verified live: EXPIRED / KICKED are reported to the first request only.
            reported, session.state = session.state, 0
            if name == "login_query":
                return web.json_response({"result": True, "login": reported})

        if name == "token_query":
            return web.json_response({"result": True, "RequestVerifyToken": self._rotate(session)})
        if name == "login_query":
            return web.json_response({"result": True, "login": session.state})
        if name == "logout_req":
            if not session.logged_in:
                return self._unauthenticated()
            session.logged_in, session.state = False, 0
            return web.json_response({"result": True})
        if name == "login_req":
            return self._login(session, body)

        # authenticated read endpoints
        if not session.logged_in:
            return self._unauthenticated()
        sent = body.get("RequestVerifyToken") if isinstance(body, dict) else None
        if name == "req_smsReload":  # validated but not rotated by the firmware
            if sent != session.token:
                return web.json_response({"result": False, "error": "Invalid token."})
            return web.json_response(json.loads(load_fixture("sms_reload.json")))
        if sent != session.token:
            return web.json_response(
                {
                    "result": False,
                    "error": "Invalid token.",
                    "RequestVerifyToken": self._rotate(session),
                }
            )
        fixture = {
            "net_status_retrieve": "net_status.json",
            "client_status_retrieve": "client_status.json",
        }.get(name)
        if fixture is None:
            return web.Response(status=404)
        data = json.loads(load_fixture(fixture))
        data["RequestVerifyToken"] = self._rotate(session)
        return web.json_response(data)

    def _unauthenticated(self) -> web.Response:
        # The real firmware leaks a CGI header into the body (no content-type) and
        # rotates the session cookie.
        resp = web.Response(body=b"Set-Cookie: QSESSIONID=deadbeef; path=/;\r\n\r\n")
        resp.set_cookie("QSESSIONID", self._new_session().sid)
        return resp

    def _login(self, session: FakeSession, body: Any) -> web.Response:
        if self.token_not_init:
            self.token_not_init -= 1
            return web.json_response(
                {
                    "result": False,
                    "error": "Token not init.",
                    "RequestVerifyToken": self._rotate(session),
                }
            )
        if self.failed_logins >= self.lock_after:
            return web.json_response(
                {
                    "result": False,
                    "error": "Refuse login",
                    "lock_time": 300,
                    "RequestVerifyToken": self._rotate(session),
                }
            )
        ok = (
            body.get("RequestVerifyToken") == session.token
            and body.get("usr") == USERNAME
            and body.get("pwd") == PASSWORD
        )
        if not ok:
            self.failed_logins += 1
            return web.json_response(
                {
                    "result": False,
                    "error": "Login fail",
                    "RequestVerifyToken": self._rotate(session),
                }
            )
        self.kick_all()
        for other in self.sessions.values():
            if other.state == 2:  # verified live: a new login wipes expired sessions
                other.state = 0
        session.logged_in, session.state = True, 1
        return web.json_response(
            {"result": True, "default_login": False, "RequestVerifyToken": self._rotate(session)}
        )


@pytest.fixture
def router() -> FakeRouter:
    return FakeRouter()


@pytest.fixture
async def server(router: FakeRouter) -> AsyncIterator[TestServer]:
    srv = TestServer(router.app())
    await srv.start_server()
    yield srv
    await srv.close()


ClientFactory = Callable[..., Awaitable[Id525Client]]


@pytest.fixture
async def make_client(server: TestServer) -> AsyncIterator[ClientFactory]:
    created: list[Id525Client] = []

    async def factory(**kwargs: Any) -> Id525Client:
        kwargs.setdefault("password", PASSWORD)
        client = Id525Client(f"{server.host}:{server.port}", USERNAME, scheme="http", **kwargs)
        created.append(client)
        return client

    yield factory
    for client in created:
        await client.close()
