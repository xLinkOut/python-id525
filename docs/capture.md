# Offline UI capture: how write operations are proven

The router is a production device and is **never** contacted to evaluate
behaviour. Instead, every request body the client sends is proven identical to
what the router's own web UI sends, by running the UI code offline.

## Pieces

| Piece | Role |
|---|---|
| `tests/fixtures/<page>.html` | anonymised UI pages (data replaced, UI code untouched) |
| `tools/uicapture/synthetic/` | page variants with invented table rows (`tests/fixtures/synthetic/`) |
| `tools/uicapture/mockrouter.py` | 127.0.0.1-only mock: serves pages + UI scripts, records every POST |
| `tools/uicapture/guard.py` | browser network guards (routing, dead proxy, no DNS) |
| `tools/uicapture/scenarios/` | one module per page: UI interactions + equivalent client calls |
| `tests/golden/<scenario>.json` | captured requests, replayed against the client by `tests/test_golden.py` |

The router's vendor UI scripts (`js/*.js`) are **not** in this repository; the
capture reads them from a local copy (`--assets`, default `../research/raw`).
Bootstrap and i18next are replaced by small shims (`tools/uicapture/shims`).

## Adding an operation

1. Read the page's code in `tests/fixtures/<page>.html`: what builds the
   request (keys, order, types, encodings), what is validated first, what the
   UI does with the answer.
2. Write scenarios in `tools/uicapture/scenarios/<page>.py`: at least two
   sending scenarios with different values (spaces, `&`, `%`, quotes,
   non-ASCII where the UI allows them) and refused scenarios for each UI
   validation. If the flow branches on answers, declare them in `answers`.
3. Capture: `uv run python -m tools.uicapture.capture --assets <raw dir> <names>`.
   The run fails if a guard blocked anything, if the UI called an endpoint
   missing from `id525.endpoints`, or if a refused scenario sent something.
4. Implement the method in `src/id525/sections/<section>.py`:
   - decorate with `@uses(...)` listing the page (if read) and endpoints;
   - build bodies with a `body(token)` function producing the UI's exact key
     order and JSON types (`int` / `str` / `bool`, never `float`);
   - port the UI's validation (raise via `invalid(...)`), in the UI's order;
   - destructive endpoints take `*, confirm: bool = False`.
5. Set the endpoint's status in `src/id525/endpoints.py`:
   `ui-captured` (real fixture), `ui-captured-synthetic` (synthetic fixture),
   `static` (implemented but no capture possible: say why in the docstring).
6. `uv run pytest`, then `uv run python -m tools.coverage_map`.

## Golden format

`requests` is the ordered list of every *mutating* request (actions, writes,
destructive) the flow sent; reads and session plumbing are listed in
`other_calls` for information only. The client, given `inputs` (+
`call_kwargs`) and the same `answers` and fixture, must send exactly that list.
`capture --check` re-captures without writing and fails on any difference.
