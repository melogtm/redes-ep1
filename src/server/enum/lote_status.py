"""Estados possíveis de um lote."""

from enum import Enum


class LoteStatus(Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
