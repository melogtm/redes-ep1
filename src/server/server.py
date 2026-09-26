"""Ponto de entrada do servidor de leilão.

Uso, a partir de src/:
    python3 -m server.server [--port 8080] [--keys ...] [--lots ...] [--debug]
"""

import argparse
import logging
import socket
import threading
import time
from pathlib import Path

from server.utils.client import lidar_com_cliente
from server.utils.utils import (
    carregar_chaves,
    carregar_lotes,
    monitorar_lote_fechamento,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

log = logging.getLogger("servidor")


def main() -> None:
    """Carrega chaves e lotes, abre a porta e cria uma thread por cliente."""

    parser = argparse.ArgumentParser()

    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--keys", type=str, default=str(PROJECT_ROOT / "resources/keys/keys.conf")
    )
    parser.add_argument(
        "--lots", type=str, default=str(PROJECT_ROOT / "resources/keys/lots.conf")
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="mostra também as mensagens brutas do protocolo",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    chaves = carregar_chaves(args.keys)
    lotes = carregar_lotes(args.lots)

    log.info("loaded %d keys and %d lots", len(chaves), len(lotes))
    for lote in lotes.values():
        fim = time.strftime("%H:%M:%S", time.localtime(lote.tempo_fim))
        log.info(
            "lote %d: %s | R$ %.2f | fecha às %s",
            lote.id,
            lote.descricao,
            lote.preco_atual,
            fim,
        )

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Permite reiniciar o servidor sem esperar a liberação da porta anterior.
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    s.bind(("0.0.0.0", args.port))
    s.listen()

    # O monitor roda em segundo plano para fechar lotes sem bloquear clientes.
    thr = threading.Thread(target=monitorar_lote_fechamento, args=(lotes,), daemon=True)
    thr.start()

    log.info("listening on port %d", args.port)

    while True:
        conn, endereco = s.accept()

        threading.Thread(
            target=lidar_com_cliente,
            args=(conn, endereco, lotes, chaves),
            daemon=True,
        ).start()


if __name__ == "__main__":
    main()
