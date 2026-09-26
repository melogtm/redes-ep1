import logging
import socket

from server.model.sessao import Sessao
from server.utils.auths import comando_autenticar, comando_login
from server.utils.protocolo import LineBuffer, ler_mensagem
from server.utils.utils import (
    comando_entrar,
    comando_lance,
    comando_listar,
    enviar_mensagem,
)

TIMEOUT_SEGUNDOS = 40

# Limita cada leitura; o LineBuffer recompõe mensagens maiores ou fragmentadas.
TAMANHO_BUFFER = 4096

log = logging.getLogger("servidor")


def lidar_com_cliente(
    conn: socket.socket, endereco: tuple[str, int], lotes: dict, chaves: dict
) -> None:
    sessao = Sessao(conn, endereco)
    buf = LineBuffer()
    motivo = "conexão encerrada"

    conn.settimeout(TIMEOUT_SEGUNDOS)
    log.info("nova conexão de %s:%d", endereco[0], endereco[1])

    try:
        while True:
            try:
                data = conn.recv(TAMANHO_BUFFER)
            except TimeoutError:
                motivo = f"timeout: {TIMEOUT_SEGUNDOS} s sem tráfego"
                break
            except OSError as exc:
                motivo = f"erro de rede: {exc}"
                break

            if data == b"":
                motivo = "cliente fechou a conexão (FIN)"
                break

            for linha in buf.feed(data):
                if not linha:
                    continue

                log.debug("<- %s: %s", sessao, linha)

                partes = ler_mensagem(linha)

                if not partes:
                    continue

                comando = partes[0]

                if not sessao.autenticado:
                    if comando == "LOGIN":
                        comando_login(sessao, partes, chaves)
                        if sessao.username is None:
                            motivo = "LOGIN recusado"
                            return
                    elif comando == "AUTH":
                        comando_autenticar(sessao, partes, chaves)
                        if not sessao.autenticado:
                            motivo = "autenticação recusada"
                            return
                    continue

                if comando == "LOGOUT":
                    motivo = "LOGOUT"
                    return
                elif comando == "BID":
                    comando_lance(sessao, partes, lotes, chaves)
                elif comando == "LIST":
                    comando_listar(sessao, lotes)
                elif comando == "KEEPALIVE":
                    enviar_mensagem(conn, "KEEPALIVE\n")
                elif comando == "JOIN":
                    comando_entrar(sessao, partes, lotes)
                elif comando == "AUTH":
                    comando_autenticar(sessao, partes, chaves)
                    if not sessao.autenticado:
                        motivo = "autenticação recusada"
                        return
    finally:
        for lote in lotes.values():
            with lote.lock:
                lote.inscritos.discard((conn, sessao.username))

            try:
                conn.close()
            except OSError:
                pass

        log.info("sessão %s encerrada: %s", sessao, motivo)
