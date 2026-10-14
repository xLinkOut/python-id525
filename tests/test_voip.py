from __future__ import annotations

from typing import Any

import pytest

from id525 import Id525CommandError, Id525ValidationError
from id525.sections.voip import ETH_WAN, RegistrationStatus, parse_voip_page

from .conftest import ClientFactory, FakeRouter, load_fixture


def test_parse_voip_page() -> None:
    voip = parse_voip_page(load_fixture("voip-settings.html"))
    assert voip.registration_status is RegistrationStatus.UP
    assert voip.sip_domain == "telecomitalia.it"
    assert voip.account == "+390000000000"  # URI-decoded like the UI does
    assert voip.phone_number is None
    assert voip.password_blob.startswith("FAKE")
    assert (voip.dns_srv, voip.line_enabled, voip.pos_mode) == (False, True, False)
    assert [a.apn for a in voip.apns] == ["fwanat.tim.it", "fwavoip.tim.it"]
    assert voip.bound_apn == "fwavoip.tim.it"
    assert voip.eth_wan is False


async def test_get_settings(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    assert (await client.voip.get_settings()).bind_interface == 2
    assert router.count("page:voip-settings") == 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"phone_number": "1", "bind_interface": "nope.apn"}, "not an enabled APN"),
        ({"phone_number": "1", "bind_interface": ETH_WAN}, "no Ethernet WAN"),
    ],
)
async def test_refused_bindings(
    kwargs: dict[str, Any], message: str, make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ValidationError, match=message):
        await client.voip.update(**kwargs)
    assert "voip_apply" not in router.calls


async def test_router_error_code(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers["voip_apply"] = {"result": False, "error_code": 17}
    client = await make_client(read_only=False)
    with pytest.raises(Id525CommandError, match="17"):
        await client.voip.update(phone_number="0000111222")
