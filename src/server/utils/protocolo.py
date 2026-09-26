"""Leitura das linhas do protocolo e cálculo do HMAC."""

import hashlib
import hmac


class LineBuffer:
    """Junta os bytes recebidos e devolve apenas linhas completas."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[str]:
        """Acrescenta data ao buffer e devolve as linhas já terminadas em LF."""
        # TCP entrega um fluxo: uma leitura pode conter várias mensagens ou
        # apenas parte de uma.
        self._buf.extend(data)

        partes = self._buf.split(b"\n")

        self._buf = partes.pop()

        return [p.decode() for p in partes if p]


def ler_mensagem(linha: str) -> list[str]:
    """Separa uma linha em campos.

    Um campo iniciado por ':' vai até o fim da linha, com espaços:
    'LOT 2 OPEN 50.00 1790448485 :Lote longo' vira
    ['LOT', '2', 'OPEN', '50.00', '1790448485', 'Lote longo'].
    """
    linha = linha.strip()
    if not linha:
        return []

    partes = linha.split(maxsplit=1)
    comando = partes[0]
    if len(partes) == 1:
        return [comando]

    corpo = partes[1]
    # O prefixo ':' marca o último campo, que pode conter espaços.
    if " :" in corpo:
        campos, trailing = corpo.split(" :", maxsplit=1)
        return [comando, *campos.split(), trailing]

    return [comando, *corpo.split()]


def assinar_lance_string(lote_id: str, preco: str, seq: str, nonce: str) -> str:
    """Texto que o cliente assina em cada BID; precisa ser idêntico dos dois lados."""
    return f"LANCE {lote_id} {preco} {seq} {nonce}"


def assinar_bytes(key: bytes, data: bytes) -> str:
    """HMAC-SHA256 de data com a chave key, em hexadecimal minúsculo."""
    return hmac.new(key, data, hashlib.sha256).hexdigest()
