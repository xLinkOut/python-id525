"""Per-page API sections, attached to :class:`id525.Id525Client` as attributes."""

from .base import Section
from .cellular import CellularApi
from .lan import DhcpReservation, LanApi, LanSettings
from .software import SoftwareApi
from .system import SystemApi

SECTIONS: dict[str, type[Section]] = {
    "cellular": CellularApi,
    "lan": LanApi,
    "software": SoftwareApi,
    "system": SystemApi,
}
"""Client attribute name -> section class."""

__all__ = [
    "SECTIONS",
    "CellularApi",
    "DhcpReservation",
    "LanApi",
    "LanSettings",
    "Section",
    "SoftwareApi",
    "SystemApi",
]
