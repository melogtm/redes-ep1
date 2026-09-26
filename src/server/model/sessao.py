"""Estado de uma conexão de cliente no servidor."""

import socket


class Sessao:
    """Autenticação, nonce, próximo seq e lotes inscritos de uma conexão."""

    def __init__(self, conn: socket.socket, endereco: tuple[str, int]):
        self.conn = conn
        self.endereco = endereco
        self.username: str | None = None
        self.autenticado = False
        self.nonce: str | None = None
        self.nonce_consumido = False
        self.proximo_seq = 1
        self.lotes_inscritos = (
            set()
        )  # Conjunto de IDs de lotes nos quais o usuário está inscrito

    def __str__(self) -> str:
        # Identifica a sessão nos logs, ex.: alice@192.168.1.12:53422
        ip, porta = self.endereco[0], self.endereco[1]
        return f"{self.username or '?'}@{ip}:{porta}"
