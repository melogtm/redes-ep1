from __future__ import annotations

import hashlib
import hmac
import re
from decimal import Decimal, InvalidOperation


_HEX_32 = re.compile(r"^[0-9a-fA-F]{32}$")


class ErroProtocolo(ValueError):
    pass


class LineBuffer:
    """Reconstrói linhas LF recebidas pelo fluxo TCP.

    TCP não preserva limites de mensagens: um recv() pode conter uma parte
    de uma linha ou várias linhas. Por isso os bytes ficam acumulados até LF.
    """

    def __init__(self, tamanho_maximo_linha: int = 64 * 1024):
        self._buf = bytearray()
        self._max = tamanho_maximo_linha

    def feed(self, data: bytes) -> list[str]:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data deve ser bytes")

        self._buf.extend(data)

        partes = self._buf.split(b"\n")
        self._buf = bytearray(partes.pop())

        linhas: list[str] = []

        for parte in partes:
            if len(parte) > self._max:
                raise ErroProtocolo(
                    "linha recebida excede o limite configurado"
                )

            if not parte:
                continue

            try:
                linhas.append(
                    parte.decode("utf-8", errors="strict")
                )
            except UnicodeDecodeError as exc:
                raise ErroProtocolo(
                    "servidor enviou texto que não é UTF-8 válido"
                ) from exc

        # Também protege contra uma linha maliciosa que nunca envia \n.
        if len(self._buf) > self._max:
            raise ErroProtocolo(
                "linha parcial excede o limite configurado"
            )

        return linhas


def ler_mensagem(linha: str) -> list[str]:
    """Aplica a mesma regra de parsing usada pelo protocolo.

    Um campo final precedido por ':' pode conter espaços. Exemplo:

        LOT 1 OPEN 100.00 1234567890 :Notebook gamer usado

    retorna:

        [
            "LOT",
            "1",
            "OPEN",
            "100.00",
            "1234567890",
            "Notebook gamer usado",
        ]
    """

    linha = linha.strip()

    if not linha:
        return []

    partes = linha.split(maxsplit=1)
    comando = partes[0]

    if len(partes) == 1:
        return [comando]

    corpo = partes[1]

    if " :" in corpo:
        campos, trailing = corpo.split(" :", maxsplit=1)

        return [
            comando,
            *campos.split(),
            trailing,
        ]

    return [
        comando,
        *corpo.split(),
    ]


def assinar(chave: str, texto: str) -> str:
    """Calcula HMAC-SHA256 em hexadecimal minúsculo."""

    return hmac.new(
        chave.encode(),
        texto.encode(),
        hashlib.sha256,
    ).hexdigest()


def texto_assinado_lance(
    lote_id: int,
    preco_enviado: str,
    seq: int,
    nonce: str,
) -> str:
    # Esta string deve coincidir EXATAMENTE com a construída pelo servidor.
    return f"LANCE {lote_id} {preco_enviado} {seq} {nonce}"


def validar_nonce(nonce: str) -> None:
    # O protocolo define nonce = 16 bytes = 32 caracteres hexadecimais.
    if not _HEX_32.fullmatch(nonce):
        raise ErroProtocolo(
            "CHALLENGE contém nonce fora do formato esperado"
        )


def normalizar_preco(valor: str | Decimal) -> str:
    """Valida preço e produz exatamente duas casas decimais.

    Exemplos:

        "150"    -> "150.00"
        "150.5"  -> "150.50"
        "150.50" -> "150.50"

    Não arredondamos silenciosamente 150.999 para 151.00 porque o texto do
    preço faz parte da assinatura HMAC do BID.
    """

    try:
        preco = (
            valor
            if isinstance(valor, Decimal)
            else Decimal(str(valor).strip())
        )
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("preço inválido") from exc

    if not preco.is_finite() or preco <= 0:
        raise ValueError(
            "preço deve ser um decimal finito e maior que zero"
        )

    centavos = Decimal("0.01")
    quantizado = preco.quantize(centavos)

    if quantizado != preco:
        raise ValueError(
            "preço deve ter no máximo duas casas decimais"
        )

    return format(quantizado, ".2f")
