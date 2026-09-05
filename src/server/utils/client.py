import socket

from server.model.sessao import Sessao
from server.utils.auths import comando_autenticar, comando_login
from server.utils.protocolo import LineBuffer, ler_mensagem
from server.utils.utils import (
    comando_entrar,
    comando_lance,
    comando_listar,
)

TIMEOUT_SEGUNDOS = 40

# Limita cada leitura; o LineBuffer recompõe mensagens maiores ou fragmentadas.
TAMANHO_BUFFER = 4096


def lidar_com_cliente(conn: socket.socket, lotes: dict, chaves: dict) -> None:
    sessao = Sessao(conn)
    buf = LineBuffer()

    conn.settimeout(TIMEOUT_SEGUNDOS)

    try:
        while True:
            try:
                data = conn.recv(TAMANHO_BUFFER)
            except TimeoutError:
                break

            if data == b"":
                break

            for linha in buf.feed(data):
                if not linha:
                    continue

                partes = ler_mensagem(linha)

                if not partes:
                    continue

                comando = partes[0]

                if not sessao.autenticado:
                    if comando == "LOGIN":
                        comando_login(sessao, partes, chaves)
                    elif comando == "AUTH":
                        comando_autenticar(sessao, partes, chaves)
                        if not sessao.autenticado:
                            return
                    continue

                if comando == "LOGOUT":
                    return
                elif comando == "BID":
                    comando_lance(sessao, partes, lotes, chaves)
                elif comando == "LIST":
                    comando_listar(sessao, lotes)
                elif comando == "KEEPALIVE":
                    conn.send(b"KEEPALIVE\n")
                elif comando == "JOIN":
                    comando_entrar(sessao, partes, lotes)
                elif comando == "AUTH":
                    comando_autenticar(sessao, partes, chaves)
                    if not sessao.autenticado:
                        return
    finally:
        for lote in lotes.values():
            with lote.lock:
                lote.inscritos.discard((conn, sessao.username))

            try:
                conn.close()
            except OSError:
                pass
