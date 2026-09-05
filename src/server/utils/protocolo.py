import hashlib
import hmac


class LineBuffer:
    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[str]:
        # TCP entrega um fluxo: uma leitura pode conter várias mensagens ou
        # apenas parte de uma.
        self._buf.extend(data)

        partes = self._buf.split(b"\n")

        self._buf = partes.pop()

        return [p.decode() for p in partes if p]


def ler_mensagem(linha: str) -> list[str]:
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
    # O cliente deve assinar exatamente este texto para o servidor validar o lance.
    return f"LANCE {lote_id} {preco} {seq} {nonce}"


def assinar(key: str, data: str) -> str:
    return hmac.new(key.encode(), data.encode(), hashlib.sha256).hexdigest()


def assinar_bytes(key: bytes, data: bytes) -> str:
    return hmac.new(key, data, hashlib.sha256).hexdigest()
