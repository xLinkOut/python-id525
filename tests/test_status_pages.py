from __future__ import annotations

from id525.sections.status import StatusApi, parse_sim_pin_page

from .conftest import ClientFactory, FakeRouter, load_fixture


def test_parse_sim_pin_page() -> None:
    pin = parse_sim_pin_page(load_fixture("net-status.html"))
    assert pin.pin_enabled is False
    assert pin.pin_retries == 3
    assert pin.puk_retries == 10


def test_missing_values_are_none() -> None:
    pin = parse_sim_pin_page("<html></html>")
    assert (pin.pin_enabled, pin.pin_retries, pin.puk_retries) == (None, None, None)


async def test_get_sim_pin_status(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client()
    pin = await StatusApi(client).get_sim_pin_status()
    assert pin.pin_retries == 3
    assert router.count("page:net-status") == 1
