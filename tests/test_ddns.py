from __future__ import annotations

import pytest

from id525 import Id525ValidationError

from .conftest import ClientFactory, FakeRouter

CONFIG = {
    "ddns_enable": "1",
    "ddns_host_name": "myhome.example.org",
    "ddns_user_name": "user",
    "ddns_password": "pw",
    "ddns_url": "afraid.org-v2-basic",
}


async def test_get_settings(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers["get_ddns_config"] = CONFIG
    client = await make_client()
    ddns = await client.ddns.get_settings()
    assert ddns.enabled is True
    assert (ddns.hostname, ddns.username, ddns.password) == ("myhome.example.org", "user", "pw")
    assert ddns.server == "afraid.org-v2-basic"
    assert ddns.status == "nointer"
    assert router.count("get_ddns_config") == 1


async def test_get_ddns_config_is_a_read(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers["get_ddns_config"] = CONFIG
    client = await make_client()  # read-only
    assert (await client.ddns.get_settings()).enabled


async def test_unknown_server_is_refused_before_anything(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match="provider"):
        await client.ddns.set_settings(server="example.com")
    assert router.calls == []


async def test_afraid_alias_is_sent_as_v2(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers["get_ddns_config"] = {**CONFIG, "ddns_url": "afraid.org"}
    client = await make_client(read_only=False)
    await client.ddns.set_settings(password="new")
    body = dict(router.bodies)["set_ddns_config"]
    assert b'"DDNS_Server":"afraid.org-v2-basic"' in body
    assert b'"DDNS_Auth":"new"' in body
