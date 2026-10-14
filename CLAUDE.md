# python-id525 — rules for Claude sessions

Async client + CLI for the General Mobile ID525 router. Read the README first
(coverage map, safety model, development commands) and `docs/capture.md`
before touching writes.

## The router is never contacted by Claude

- No live call to a real router, ever, reads included, unless the user lifts
  the ban explicitly in the current conversation. The CLI's default host *is*
  the real router: never run `id525` except against the in-process fake router
  (tests) or a loopback mock.
- Live testing is the user's job. To check or debug a feature, give the user
  the exact command, always with `--trace` (read-only first; `--write` /
  `--confirm` only when the feature needs it). Say what it will change on the
  router before they run it.
- The trace path is printed on stderr (default `~/.cache/id525/traces/`). Read
  the file directly from there; you don't need the user to paste it.
- Login lockout: if a trace shows a login error other than `Token not init.`,
  tell the user to stop. Never suggest retrying credentials in a loop.

## Debugging from a trace

1. Read the whole trace: `start` (version, commit, `-dirty`), `call`
   (operation + kwargs), one `http` event per exchange (exact request body,
   raw answer, status, ms, transport error), `log`, then `result` or `error`
   (with traceback).
2. Pseudonyms (`TOKEN-3`, `SECRET-1`, `MAC-2`, `02:00:5e:10:..`, `203.0.113.x`,
   same-length digit strings) are not real values. The same pseudonym means the
   same original value throughout one trace (e.g. a reused CSRF token).
3. Reproduce offline first: put the answer the router gave into the fake
   router (`tests/conftest.py`) or a fixture, write the failing test, then fix.
4. Anything from a trace that goes into the repo is device data until proven
   otherwise. Check it for identifying values (the redaction is best effort)
   and anonymise it before committing.
5. Only when a user trace proves a behaviour can an endpoint's registry status
   become `live-verified`. Note the evidence (date, firmware) in its notes.

## Registry and safety model (don't weaken)

- `src/id525/endpoints.py` is the allow-list. Every endpoint and page has a
  `Kind` and a `Status`. The client can't reach anything that isn't listed,
  and the README map is generated from it.
- The client is read-only by default. Mutating calls need `read_only=False`,
  and destructive ones also need `confirm=True`. Checks run before any byte is
  sent (`@uses`, `check_allowed`, `_post`); `tests/test_safety.py` guards this.
- If a behaviour can't be derived offline, it stays a stub raising
  `NotImplementedError`.
- Unsupported by the user's decision: factory reset, firmware flashing,
  config backup/restore, SIM PIN/PUK. Keep them unsupported unless the user
  says otherwise. Reboot is supported.

## Writes are proven by goldens

- Every write body must equal what the router's own UI sends. Add a scenario
  in `tools/uicapture/scenarios`, capture it, then implement until
  `tests/test_golden.py` passes. Never hand-write or hand-edit a golden.
- Changing a page fixture invalidates its goldens (`fixture_sha256`):
  recapture them.
- The router's UI JS is never committed. The capture reads it from a local
  copy (`--assets`).
- The capture sandbox has 3 network guards (`tests/uicapture/test_guards.py`).
  Don't relax them, and rerun the browser tests after any change to
  `tools/uicapture`.

## Personal data

- Fixtures come from real pages with every identifying value replaced (IMEI,
  IMSI, ICCID, serials, phone numbers, SMS texts, cell ids, MACs, SSIDs,
  Wi-Fi/VoIP/DDNS credentials, device names, public IPs). Add a post-condition
  for every new field.
- If real data was ever committed, anonymising isn't enough: also rewrite the
  history (`uvx git-filter-repo --force --replace-text <file>` over all refs),
  then scan every object (reflog, unreachable) for the originals.
  `filter-repo` removes `origin`: re-add it. Never force-push without asking.
- After changing `src/id525/trace.py`, run the redactor over the real dumps
  (they live outside this repo) and check that 0 original values survive.
  Do it offline, and don't save its output in the repo.

## Workflow

- Work on a branch. Never push, tag or publish (PyPI) unless the user asks.
- Before saying "done", run:
  ```bash
  uv run ruff check . && uv run ruff format --check . && uv run mypy
  uv run pytest -m "not browser"
  uv run pytest -m browser --no-cov                       # if tools/uicapture changed
  uv run python -m tools.uicapture.capture --assets <UI copy> --check  # if fixtures/scenarios changed (~7 min)
  uv run python -m tools.coverage_map                     # if the registry changed; commit the result
  ```
- The user writes in Italian: reply in Italian. Code, docs and commit messages
  are in English.
