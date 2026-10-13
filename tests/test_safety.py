"""Safety model: read-only by default, explicit confirmation, unsupported stubs."""

from __future__ import annotations

import inspect

import pytest

from id525 import (
    Id525Client,
    Id525CommandError,
    Id525ConfirmationRequiredError,
    Id525ReadOnlyError,
)
from id525.endpoints import ENDPOINTS, PAGES, Endpoint, Kind, Page, Status
from id525.operations import operations
from id525.sections import SECTIONS

from .conftest import ClientFactory, FakeRouter

MUTATING_OPS = [op for op in operations() if op.kind.mutating and op.implemented]
STUB_OPS = [op for op in operations() if not op.implemented]
DUMMY_ARGS = {
    "name": "x",
    "ip": "192.168.224.50",
    "mac": "02:00:5e:00:00:99",
    "index": 1,
    "role": "wan",
}


def call_args(func: object) -> dict[str, object]:
    """Plausible arguments for an operation (confirmed, if it asks for it)."""
    params = inspect.signature(func).parameters  # type: ignore[arg-type]
    args: dict[str, object] = {
        name: DUMMY_ARGS[name]
        for name, p in params.items()
        if name != "self" and p.default is inspect.Parameter.empty
    }
    if "confirm" in params:
        args["confirm"] = True
    return args


def bound(client: Id525Client, path: str) -> object:
    target: object = client
    for part in path.split("."):
        target = getattr(target, part)
    return target


def test_client_is_read_only_by_default() -> None:
    assert Id525Client().read_only is True


@pytest.mark.parametrize("op", MUTATING_OPS, ids=lambda op: op.path)
async def test_read_only_client_refuses_before_sending_anything(
    op: object, make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client()
    method = bound(client, op.path)  # type: ignore[attr-defined]
    with pytest.raises(Id525ReadOnlyError):
        await method(**call_args(method))  # type: ignore[operator]
    assert router.calls == []  # not even a login


@pytest.mark.parametrize("op", STUB_OPS, ids=lambda op: op.path)
async def test_stubs_raise_without_sending(
    op: object, make_client: ClientFactory, router: FakeRouter
) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(NotImplementedError):
        await bound(client, op.path)()  # type: ignore[attr-defined,operator]
    assert router.calls == []


async def test_post_refuses_unsupported_endpoints(make_client: ClientFactory) -> None:
    """Defence in depth: the transport itself refuses, whatever the caller."""
    client = await make_client(read_only=False)
    with pytest.raises(NotImplementedError):
        await client._post(Endpoint.RESTORE_DEFAULT, {}, confirmed=True)
    with pytest.raises(NotImplementedError):
        await client._post(Endpoint.PIN_ENTER, {})


async def test_post_refuses_writes_on_read_only_client(make_client: ClientFactory) -> None:
    client = await make_client()
    with pytest.raises(Id525ReadOnlyError):
        await client._post(Endpoint.DHCP_RESERVATION_DELETE, {})


async def test_reboot_needs_confirmation(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client(read_only=False)
    with pytest.raises(Id525ConfirmationRequiredError):
        await client.system.reboot()
    with pytest.raises(Id525ConfirmationRequiredError):
        await client._post(Endpoint.REBOOT, {})
    assert router.calls == []


async def test_reboot_forgets_the_session(make_client: ClientFactory, router: FakeRouter) -> None:
    client = await make_client(read_only=False)
    await client.system.reboot(confirm=True)
    assert router.count("reboot") == 1
    assert not client.is_logged_in


async def test_reboot_tolerates_a_dropped_connection(
    make_client: ClientFactory, router: FakeRouter
) -> None:
    router.drop.add("reboot")
    client = await make_client(read_only=False)
    await client.system.reboot(confirm=True)
    assert router.count("reboot") == 1
    assert not client.is_logged_in


async def test_rejected_command_raises(make_client: ClientFactory, router: FakeRouter) -> None:
    router.answers["reboot"] = {"result": False, "error": "busy"}
    client = await make_client(read_only=False)
    with pytest.raises(Id525CommandError, match="busy"):
        await client.system.reboot(confirm=True)


def test_registry_is_complete() -> None:
    assert set(ENDPOINTS) == set(Endpoint)
    assert set(PAGES) == set(Page)


def test_every_supported_or_stubbed_endpoint_has_an_operation() -> None:
    used = {t for op in operations() for t in op.endpoints}
    needed = {e for e in Endpoint if e.info.status not in (Status.PLANNED, Status.DEAD_CODE)}
    assert needed - used == set()
    assert {e for e in used if e.info.status in (Status.PLANNED, Status.DEAD_CODE)} == set()


def test_implemented_pages_have_an_operation() -> None:
    used = {t for op in operations() for t in op.targets if isinstance(t, Page)}
    assert {p for p in Page if p.info.status.implemented} <= used


def test_destructive_operations_take_a_confirm_flag() -> None:
    for op in operations():
        if op.kind is Kind.DESTRUCTIVE and op.implemented:
            param = inspect.signature(op.function).parameters.get("confirm")
            assert param is not None, op.path
            assert param.kind is inspect.Parameter.KEYWORD_ONLY
            assert param.default is False


def test_sections_are_attached_to_the_client() -> None:
    client = Id525Client()
    for name, cls in SECTIONS.items():
        assert isinstance(getattr(client, name), cls)
