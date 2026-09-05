import socket


class Sessao:
    def __init__(self, conn: socket.socket):
        self.conn = conn
        self.username: str | None = None
        self.autenticado = False
        self.nonce: str | None = None
        self.nonce_consumido = False
        self.proximo_seq = 1
        self.lotes_inscritos = (
            set()
        )  # Conjunto de IDs de lotes nos quais o usuário está inscrito
