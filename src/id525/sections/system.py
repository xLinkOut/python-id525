"""System operations from the ``adm-backup`` page: reboot, backup, factory reset."""

from __future__ import annotations

from typing import NoReturn

from ..endpoints import Endpoint, uses
from ..exceptions import Id525CommandError
from .base import Section


class SystemApi(Section):
    """Reboot and the (deliberately unsupported) backup / reset operations."""

    @uses(Endpoint.REBOOT)
    async def reboot(self, *, confirm: bool = False) -> None:
        """Reboot the router. Destructive: needs ``confirm=True``.

        The router may drop the connection while answering (the UI ignores the
        answer and reloads the login page after 50 s), so a transport error on
        this call is not an error. The session dies with the reboot.
        """
        data = await self._client._call(
            Endpoint.REBOOT, confirmed=confirm, tolerate_disconnect=True
        )
        self._client._forget_session()
        if data.get("result") is False:
            raise Id525CommandError(Endpoint.REBOOT, data.get("error"))

    @uses(Endpoint.RESTORE_DEFAULT)
    async def factory_reset(self) -> NoReturn:
        """Not supported: irreversible (wipes every setting)."""
        self._unsupported(Endpoint.RESTORE_DEFAULT)

    @uses(Endpoint.BACKUP_CONFIG)
    async def backup_config(self) -> NoReturn:
        """Not supported: hidden in this firmware, output format unknown offline."""
        self._unsupported(Endpoint.BACKUP_CONFIG)

    @uses(Endpoint.RESTORE_CONFIG, Endpoint.UPLOAD_FILE)
    async def restore_config(self) -> NoReturn:
        """Not supported: overwrites the whole configuration from a file."""
        self._unsupported(Endpoint.RESTORE_CONFIG)
