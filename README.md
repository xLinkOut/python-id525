# python-id525

Async, **read-only** Python client for the **General Mobile ID525** 5G FWA
router (sold in Italy by TIM as *FWA 5G*), talking to the same JSON/CGI API the
router's web UI uses.

> Unofficial project, not affiliated with General Mobile or TIM.

## Features

- Network status: SIM/registration state, signal level, operator, connection
  time, data counters, WAN IPv4/IPv6, Wi-Fi state and client counts, Ethernet
  link speeds.
- Serving cells: 4G/5G band, bandwidth, PCI, ARFCN, cell id, RSRP/RSRQ/SNR.
- Utilisation: CPU and memory (current/min/max), uplink/downlink throughput,
  uptime.
- Device info: model, hardware/software version, IMEI, IMSI, phone number, APNs.
- LAN client list (hostname, MAC, IP, interface).
- SMS store (never marks messages as read).
- Fully typed (`py.typed`), `asyncio` + `aiohttp`, no other dependencies.

### Read-only by design

The router is usually a production device. The client can only reach an
explicit allow-list of endpoints and pages (`id525.const.Endpoint` / `Page`),
none of which changes the router's configuration or state. Write operations
(reboot, settings, SMS sending...) are intentionally not implemented.

## Installation

```bash
uv add id525        # or: pip install id525
```

## Usage

```python
import asyncio
from id525 import Id525Client


async def main() -> None:
    async with Id525Client("192.168.224.1", "admin", "password") as router:
        status = await router.get_network_status()
        cells = await router.get_cellular_info()
        print(status.sim_state, status.operation_mode, status.signal_level)
        if (nr := cells.primary_5g) is not None:
            print(nr.band, nr.rsrp, nr.rsrq, nr.snr)


asyncio.run(main())
```

### Command line

```bash
export ID525_USERNAME=admin ID525_PASSWORD=...
id525 status            # also: clients cells utilization about sms session all
id525 --host 192.168.224.1 --env-file .env all
```

## Things to know about the router

These behaviours were verified on firmware `ID525_REL_1.0.09.17` and are
handled by the client:

| Behaviour | Consequence |
|---|---|
| **Single admin session**: a new login kicks out the previous one (web UI included). | Polling keeps the web UI logged out. Pause polling when you need the web UI. |
| The router reports what happened to a session (`EXPIRED`, `KICKED`) **only once**, to the first request made with it. A login by someone else after our session expired shows up as "not logged in". | Call `ensure_session()` at the start of each polling cycle: it re-logs in after a plain expiry, and raises `Id525SessionKickedError` when someone else took the session, instead of silently taking it back. |
| CSRF tokens are **single-use** and rotate on every response; loading any UI page invalidates the current one. | All requests are serialised with a lock; tokens are refreshed transparently. |
| Repeated wrong logins trigger a **login lockout**. | A rejected login is never retried automatically (`Id525AuthenticationError` / `Id525LoginLockedError`). |
| Self-signed TLS certificate. | Verification is off by default; pass `ssl_context=aiohttp.Fingerprint(...)` to pin it. |
| Sessions end 5 minutes after login (default setting), even while polling. | Expired sessions are re-established automatically (`auto_relogin=True`). |

If you pass your own `aiohttp.ClientSession`, create it with
`cookie_jar=aiohttp.DummyCookieJar()`: the client manages the session cookie
itself.

## Development

```bash
uv sync
uv run pytest            # tests run against an in-process fake router
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Test fixtures are real router responses with every identifying value replaced.

## License

MIT
