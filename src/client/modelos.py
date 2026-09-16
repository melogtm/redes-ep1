from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class StatusLote(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass(slots=True)
class LoteCliente:
    id: int
    descricao: str
    status: StatusLote
    preco_atual: Decimal
    tempo_fim: int
    lider_atual: str | None = None

    @property
    def aberto(self) -> bool:
        return self.status is StatusLote.OPEN

    def segundos_restantes(self) -> int:
        # A contagem mostrada na interface é apenas visual.
        # O epoch enviado pelo servidor continua sendo a autoridade.
        return max(
            0,
            self.tempo_fim - int(time.time()),
        )


@dataclass(frozen=True, slots=True)
class EventoCliente:
    """Evento assíncrono entregue pelo componente de rede à interface."""

    tipo: str
    mensagem: str

    lote_id: int | None = None
    preco: Decimal | None = None
    tempo_fim: int | None = None
    usuario: str | None = None
