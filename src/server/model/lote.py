"""Estado de um lote do leilão."""

import threading
import time

from server.enum.lote_status import LoteStatus


class Lote:
    """Um lote em disputa. Os campos que mudam são protegidos por lock."""

    def __init__(self, lote_id, descricao, preco_atual, duracao_segundos):
        self.id = lote_id
        self.descricao = descricao
        self.preco_atual = preco_atual
        # Usuário que lidera o lote, ou None se ainda não houve lance.
        self.lider_atual: str | None = None
        # Término em epoch Unix; o soft close pode adiá-lo.
        self.tempo_fim = time.time() + duracao_segundos
        self.status = LoteStatus.OPEN  # Status do lote (aberto ou fechado)
        self.lock = threading.Lock()  # Lock para sincronização de acesso ao lote
        # Pares (conexão, usuário) que recebem as notificações do lote. O mesmo
        # usuário conectado de dois lugares aparece duas vezes.
        self.inscritos = set()
