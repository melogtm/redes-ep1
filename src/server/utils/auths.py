import hmac
import logging
import secrets

from server.model.sessao import Sessao
from server.utils.protocolo import assinar_bytes
from server.utils.utils import enviar_mensagem, fechar_conexao

NONCE_BYTES = 16

log = logging.getLogger("servidor")


def comando_login(sessao: Sessao, partes: list, chaves: dict) -> None:

    if len(partes) < 2:
        log.info("%s: LOGIN sem usuário -> AUTH_FAIL UNKNOWN_USER", sessao)
        enviar_mensagem(sessao.conn, "AUTH_FAIL UNKNOWN_USER\n")

        fechar_conexao(sessao.conn)
        return

    username = partes[1]

    if username not in chaves:
        log.info("%s: LOGIN %s -> AUTH_FAIL UNKNOWN_USER", sessao, username)
        enviar_mensagem(sessao.conn, "AUTH_FAIL UNKNOWN_USER\n")
        fechar_conexao(sessao.conn)
        return

    sessao.username = username
    # O challenge impede reutilizar uma assinatura de uma autenticação anterior.
    sessao.nonce = secrets.token_hex(NONCE_BYTES)
    log.info("%s: LOGIN -> CHALLENGE %s", sessao, sessao.nonce)
    enviar_mensagem(sessao.conn, f"CHALLENGE {sessao.nonce}\n")


def comando_autenticar(sessao: Sessao, partes: list, chaves: dict) -> None:
    if sessao.username is None:
        log.info("%s: AUTH antes de LOGIN -> AUTH_FAIL UNKNOWN_USER", sessao)
        enviar_mensagem(sessao.conn, "AUTH_FAIL UNKNOWN_USER\n")
        fechar_conexao(sessao.conn)
        return

    if sessao.nonce_consumido or sessao.nonce is None:
        log.info("%s: AUTH com nonce já usado -> AUTH_FAIL NONCE_EXPIRED", sessao)
        enviar_mensagem(sessao.conn, "AUTH_FAIL NONCE_EXPIRED\n")
        fechar_conexao(sessao.conn)
        return

    if len(partes) < 2:
        log.info("%s: AUTH sem MAC -> AUTH_FAIL BAD_MAC", sessao)
        enviar_mensagem(sessao.conn, "AUTH_FAIL BAD_MAC\n")
        fechar_conexao(sessao.conn)
        return

    hmac_cliente = partes[1]

    esperado = assinar_bytes(chaves[sessao.username].encode(), sessao.nonce.encode())

    sessao.nonce_consumido = True

    # Comparação constante evita revelar o MAC correto por tempo de resposta.
    if not hmac.compare_digest(hmac_cliente.encode(), esperado.encode()):
        log.info("%s: AUTH com MAC incorreto -> AUTH_FAIL BAD_MAC", sessao)
        enviar_mensagem(sessao.conn, "AUTH_FAIL BAD_MAC\n")
        fechar_conexao(sessao.conn)
        return

    sessao.autenticado = True
    sessao.proximo_seq = 1
    log.info("%s: autenticado -> AUTH_OK", sessao)
    enviar_mensagem(sessao.conn, f"AUTH_OK {sessao.username}\n")
