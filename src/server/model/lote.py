import threading
import time

from server.enum.lote_status import LoteStatus


class Lote:
    def __init__(self, lote_id, descricao, preco_atual, duracao_segundos):
        self.id = lote_id
        self.descricao = descricao
        self.preco_atual = preco_atual
        self.lider_atual: str | None = (
            None  # ID do usuário que lidera o lote (ou None se não houver líder)
        )
        self.tempo_fim = time.time() + duracao_segundos
        self.status = LoteStatus.OPEN  # Status do lote (aberto ou fechado)
        self.lock = threading.Lock()  # Lock para sincronização de acesso ao lote
        self.inscritos = set()  # Conjunto de IDs de usuários inscritos no lote
