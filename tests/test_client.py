from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

from id525 import (
    Id525AuthenticationError,
    Id525Client,
    Id525ConnectionError,
    Id525LoginLockedError,
    Id525SessionExpiredError,
    Id525SessionKickedError,
    LoginState,
    SimState,
)
from id525.const import Endpoint, Page

from .conftest import PASSWORD, USERNAME, ClientFactory, FakeRouter


async def test_read_everything(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    status = await client.get_network_status()
    clients = await client.get_clients()
    cells = await client.get_cellular_info()
    util = await client.get_utilization()
    about = await client.get_device_info()
    sms = await client.get_sms()

    assert status.sim_state is SimState.CONNECTED
    assert len(clients) == 6
    assert cells.primary_5g is not None
    assert util.uptime is not None
    assert about.model == "ID525"
    assert sms.unread_count == 1
    assert client.is_logged_in
    assert router.count("login_req") == 1


async def test_login_flow_mimics_browser(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    await client.login()
    assert router.calls[:3] == ["GET /", "token_query", "login_req"]
    token_body = dict(router.bodies)["token_query"]
    assert token_body == b'"{}"'  # the UI's JSON.stringify('{}') quirk
    login_body = json.loads(dict(router.bodies)["login_req"])
    assert set(login_body) == {"RequestVerifyToken", "usr", "pwd"}


async def test_context_manager_logs_in_and_out(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    async with await make_client() as client:
        assert client.is_logged_in
        await client.get_network_status()
    assert router.count("logout_req") == 1
    assert router.admin() is None
    assert not client.is_logged_in


async def test_token_rotates_on_every_call(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    for _ in range(3):
        await client.get_network_status()
    sent = [
        json.loads(body)["RequestVerifyToken"]
        for name, body in router.bodies
        if name == "net_status_retrieve"
    ]
    assert len(set(sent)) == 3


async def test_invalid_token_is_recovered(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    await client.get_network_status()
    router.invalidate_tokens()
    await client.get_network_status()
    assert router.count("net_status_retrieve") == 3  # ok, rejected, retried
    assert router.count("login_req") == 1


async def test_page_load_invalidates_token(make_client: ClientFactory, router: FakeRouter) -> None:
    """Verified live: any page GET invalidates the token held by the client."""
    client = await make_client()
    await client.get_network_status()
    await client.get_cellular_info()
    await client.get_network_status()
    await client.get_device_info()
    await client.get_sms()  # its error answers carry no token
    assert router.count("net_status_retrieve") == 2  # never rejected
    assert router.count("req_smsReload") == 1
    assert router.count("token_query") == 3  # login + one after each page


async def test_sms_invalid_token_without_new_token(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client()
    await client.get_sms()
    router.invalidate_tokens()
    inbox = await client.get_sms()
    assert inbox.unread_count == 1
    assert router.count("req_smsReload") == 3


async def test_concurrent_calls_are_serialised(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client()
    results = await asyncio.gather(
        client.get_network_status(),
        client.get_clients(),
        client.get_network_status(),
        client.get_cellular_info(),
        client.get_sms(),
    )
    assert len(results) == 5
    assert router.count("login_req") == 1
    assert router.count("net_status_retrieve") == 2  # no token collisions


async def test_wrong_password_is_never_retried(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(password="wrong")
    with pytest.raises(Id525AuthenticationError, match="Login fail"):
        await client.get_network_status()
    # Further calls must not hit the router again (lockout protection)...
    with pytest.raises(Id525AuthenticationError, match="previous login was rejected"):
        await client.get_network_status()
    assert router.count("login_req") == 1
    # ...unless the caller explicitly asks for a new login.
    with pytest.raises(Id525AuthenticationError):
        await client.login()
    assert router.count("login_req") == 2


async def test_login_lockout(make_client: ClientFactory, router: FakeRouter) -> None:
    router.failed_logins = router.lock_after
    client = await make_client()
    with pytest.raises(Id525LoginLockedError) as exc_info:
        await client.login()
    assert exc_info.value.lock_time == 300
    assert router.count("login_req") == 1


async def test_token_not_init_is_retried(make_client: ClientFactory, router: FakeRouter) -> None:
    router.token_not_init = 2
    client = await make_client()
    await client.login()
    assert client.is_logged_in
    assert router.count("login_req") == 3


async def test_expired_session_relogs_in(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    await client.get_network_status()
    router.expire_all()
    status = await client.get_network_status()
    assert status.sim_state is SimState.CONNECTED
    assert router.count("login_query") == 1
    assert router.count("login_req") == 2


async def test_expired_session_without_auto_relogin(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(auto_relogin=False)
    await client.get_network_status()
    router.expire_all()
    with pytest.raises(Id525SessionExpiredError, match="session ended"):
        await client.get_network_status()
    assert router.count("login_req") == 1


async def test_kicked_session_is_not_retaken(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client()
    await client.get_network_status()
    router.kick_all()  # e.g. somebody logged into the web UI
    with pytest.raises(Id525SessionKickedError):
        await client.get_network_status()
    assert router.count("login_req") == 1
    assert not client.is_logged_in
    # the caller (e.g. HA after its back-off) decides when to take over again
    await client.login()
    await client.get_network_status()
    assert router.count("login_req") == 2


async def test_kicked_by_second_client_is_detected(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    """Regression (found live): A must not re-login and kick B back."""
    a = await make_client()
    b = await make_client()
    await a.get_network_status()
    await b.get_network_status()  # takes over the admin session
    with pytest.raises(Id525SessionKickedError):
        await a.get_network_status()
    assert router.count("login_req") == 2
    assert await b.get_login_state() is LoginState.LOGGED_IN
    await a.close()  # logout of a dead session must be harmless
    assert await b.get_login_state() is LoginState.LOGGED_IN


async def test_page_redirect_triggers_relogin(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client()
    await client.get_cellular_info()
    router.expire_all()
    info = await client.get_cellular_info()
    assert info.cells
    assert router.count(f"page:{Page.CELLULAR_STATUS}") == 3
    assert router.count("login_req") == 2


async def test_page_kicked(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    await client.get_device_info()
    router.kick_all()
    with pytest.raises(Id525SessionKickedError):
        await client.get_device_info()


async def test_get_login_state(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    await client.login()
    assert await client.get_login_state() is LoginState.LOGGED_IN
    router.kick_all()
    assert await client.get_login_state() is LoginState.KICKED


async def test_keep_alive_refreshes_token(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    await client.login()
    await client.keep_alive()
    assert router.count("token_query") == 2
    await client.get_network_status()


async def test_connection_error() -> None:
    client = Id525Client("127.0.0.1:9", scheme="http", request_timeout=2)
    with pytest.raises(Id525ConnectionError):
        await client.login()
    await client.close()


async def test_only_allow_listed_endpoints(make_client: ClientFactory) -> None:
    client = await make_client()
    with pytest.raises(TypeError, match="not allow-listed"):
        await client._post("reboot", "{}")  # type: ignore[arg-type]


def test_allow_list_contains_no_write_endpoint() -> None:
    """Safety guard: changing the allow-list must be a deliberate, reviewed act."""
    assert {e.value for e in Endpoint} == {
        "token_query",
        "login_req",
        "logout_req",
        "login_query",
        "net_status_retrieve",
        "client_status_retrieve",
        "req_smsReload",
    }
    assert {p.value for p in Page} == {"cellular-status", "util-status", "help-about"}


async def test_external_session_is_not_closed(server: TestServer) -> None:
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as http:
        client = Id525Client(
            f"{server.host}:{server.port}", USERNAME, PASSWORD, session=http, scheme="http"
        )
        await client.get_network_status()
        await client.close()
        assert not http.closed
