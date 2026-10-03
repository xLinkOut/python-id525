"""Exceptions raised by the ID525 client."""

from __future__ import annotations


class Id525Error(Exception):
    """Base class for all ID525 errors."""


class Id525ConnectionError(Id525Error):
    """The router could not be reached or the request timed out."""


class Id525ResponseError(Id525Error):
    """The router returned something the client could not understand."""


class Id525AuthenticationError(Id525Error):
    """The router rejected the credentials.

    The client never retries a rejected login on its own: repeated failures
    trigger the router's login lockout.
    """


class Id525LoginLockedError(Id525AuthenticationError):
    """The router is refusing logins for a while after too many failures."""

    def __init__(self, lock_time: int | None) -> None:
        self.lock_time = lock_time
        detail = f" for {lock_time} s" if lock_time is not None else ""
        super().__init__(f"router is refusing logins{detail}")


class Id525SessionError(Id525Error):
    """The admin session is no longer valid."""


class Id525SessionKickedError(Id525SessionError):
    """Another admin login (e.g. the web UI) took over the single admin session."""


class Id525SessionExpiredError(Id525SessionError):
    """The session expired and automatic re-login is disabled."""
