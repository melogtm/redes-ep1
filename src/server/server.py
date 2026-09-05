import argparse
import socket
import threading
from pathlib import Path

from server.utils.client import lidar_com_cliente
from server.utils.utils import (
    carregar_chaves,
    carregar_lotes,
    monitorar_lote_fechamento,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:

    parser = argparse.ArgumentParser()

    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--keys", type=str, default=str(PROJECT_ROOT / "resources/keys/keys.conf")
    )
    parser.add_argument(
        "--lots", type=str, default=str(PROJECT_ROOT / "resources/keys/lots.conf")
    )

    args = parser.parse_args()

    chaves = carregar_chaves(args.keys)
    lotes = carregar_lotes(args.lots)

    print(f"[SERVER] loaded {len(chaves)} keys and {len(lotes)} lots")

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Permite reiniciar o servidor sem esperar a liberação da porta anterior.
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    s.bind(("0.0.0.0", args.port))
    s.listen()

    # O monitor roda em segundo plano para fechar lotes sem bloquear clientes.
    thr = threading.Thread(target=monitorar_lote_fechamento, args=(lotes,), daemon=True)
    thr.start()

    print(f"[SERVER] listening on port {args.port}")

    while True:
        conn, _ = s.accept()

        threading.Thread(
            target=lidar_com_cliente, args=(conn, lotes, chaves), daemon=True
        ).start()


if __name__ == "__main__":
    main()
