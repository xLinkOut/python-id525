"""Local mock of the router for the UI capture (127.0.0.1 only).

Serves the anonymised page fixtures, the router UI scripts from a local asset
directory (vendor code: never committed, see ``capture.py``) and the shims, and
records every API POST the UI code sends, answering with canned JSON.
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import web

SHIMS = Path(__file__).parent / "shims"
TOKEN_PREFIX = "capture-token-"  # noqa: S105


def next_answer(answers: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Pop the canned answer for ``name`` (a list answers in turn, the last repeats)."""
    answer = answers.get(name)
    if isinstance(answer, list):
        return answer.pop(0) if len(answer) > 1 else answer[0] if answer else None
    return answer


@dataclass(frozen=True)
class Recorded:
    """One API request as it left the browser."""

    endpoint: str
    body: bytes
    content_type: str | None


@dataclass
class MockRouter:
    """aiohttp app + request log. Use :meth:`start` / :meth:`stop`."""

    pages_dir: Path
    assets_dir: Path | None
    host: str = "127.0.0.1"
    requests: list[Recorded] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    answers: dict[str, Any] = field(default_factory=dict)
    """Canned answers for the current scenario (see ``Scenario.answers``)."""
    page_fixtures: dict[str, str] = field(default_factory=dict)
    """Page name -> fixture name (relative to ``pages_dir``, no suffix) to serve."""
    _runner: web.AppRunner | None = None
    port: int = 0

    def __post_init__(self) -> None:
        if not ipaddress.ip_address(self.host).is_loopback:
            msg = f"the mock router must bind to loopback, not {self.host}"
            raise ValueError(msg)

    @property
    def origin(self) -> str:
        """Return the origin the browser is allowed to reach."""
        return f"http://{self.host}:{self.port}"

    def next_token(self) -> str:
        """Issue a fresh deterministic CSRF token."""
        token = f"{TOKEN_PREFIX}{len(self.tokens) + 1:04d}"
        self.tokens.append(token)
        return token

    def app(self) -> web.Application:
        """Build the aiohttp application."""
        app = web.Application()
        app.router.add_get("/cgi-bin/cm/{page}.html", self._page)
        app.router.add_post("/cgi-bin/cgi/{name}.cgi", self._api)
        app.router.add_get("/{path:.*}", self._static)
        return app

    async def start(self) -> None:
        """Start serving on an ephemeral loopback port."""
        self._runner = web.AppRunner(self.app())
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, 0)
        await site.start()
        self.port = self._runner.addresses[0][1]

    async def stop(self) -> None:
        """Stop serving."""
        if self._runner is not None:
            await self._runner.cleanup()

    async def _page(self, request: web.Request) -> web.StreamResponse:
        name = request.match_info["page"]
        path = self.pages_dir / f"{self.page_fixtures.get(name, name)}.html"
        if not path.is_file():
            return web.Response(text=f"<html><body>{name}</body></html>", content_type="text/html")
        return web.Response(body=path.read_bytes(), content_type="text/html", charset="utf-8")

    async def _static(self, request: web.Request) -> web.StreamResponse:
        rel = request.match_info["path"]
        shim = SHIMS / Path(rel).name
        if rel.startswith("js/") and shim.is_file():
            return web.FileResponse(shim, headers={"Content-Type": "text/javascript"})
        if self.assets_dir is not None:
            path = (self.assets_dir / rel).resolve()
            if path.is_relative_to(self.assets_dir.resolve()) and path.is_file():
                ctype = "text/javascript" if path.suffix == ".js" else None
                return web.FileResponse(path, headers={"Content-Type": ctype} if ctype else None)
        return web.Response(status=404)

    async def _api(self, request: web.Request) -> web.Response:
        name = request.match_info["name"]
        raw = await request.read()
        self.requests.append(Recorded(name, raw, request.headers.get("Content-Type")))
        canned = next_answer(self.answers, name)
        answer = self.default_answer(name)
        if canned is not None:
            answer = {"result": True, **canned, "RequestVerifyToken": self.next_token()}
        return web.Response(text=json.dumps(answer), content_type="application/json")

    def default_answer(self, name: str) -> dict[str, Any]:
        """Answer like a healthy router."""
        if name == "login_query":
            return {"login": 1}
        if name == "req_smsReload":
            return {"result": True, "sms_list": []}
        return {"result": True, "RequestVerifyToken": self.next_token()}
