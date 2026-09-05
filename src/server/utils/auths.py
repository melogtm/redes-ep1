import hmac
import secrets

from server.model.sessao import Sessao
from server.utils.protocolo import assinar_bytes
from server.utils.utils import enviar_mensagem, fechar_conexao

NONCE_BYTES = 16


def comando_login(sessao: Sessao, partes: list, chaves: dict) -> None:

    if len(partes) < 2:
        enviar_mensagem(sessao.conn, "AUTH_FAIL UNKNOWN_USER\n")

        fechar_conexao(sessao.conn)
        return

    username = partes[1]

    if username not in chaves:
        enviar_mensagem(sessao.conn, "AUTH_FAIL UNKNOWN_USER\n")
        fechar_conexao(sessao.conn)
        return

    sessao.username = username
    # O challenge impede reutilizar uma assinatura de uma autenticação anterior.
    sessao.nonce = secrets.token_hex(NONCE_BYTES)
    enviar_mensagem(sessao.conn, f"CHALLENGE {sessao.nonce}\n")


def comando_autenticar(sessao: Sessao, partes: list, chaves: dict) -> None:
    if sessao.username is None:
        enviar_mensagem(sessao.conn, "AUTH_FAIL UNKNOWN_USER\n")
        fechar_conexao(sessao.conn)
        return

    if sessao.nonce_consumido or sessao.nonce is None:
        enviar_mensagem(sessao.conn, "AUTH_FAIL NONCE_EXPIRED\n")
        fechar_conexao(sessao.conn)
        return

    if len(partes) < 2:
        enviar_mensagem(sessao.conn, "AUTH_FAIL BAD_MAC\n")
        fechar_conexao(sessao.conn)
        return

    hmac_cliente = partes[1]

    esperado = assinar_bytes(chaves[sessao.username].encode(), sessao.nonce.encode())

    sessao.nonce_consumido = True

    # Comparação constante evita revelar o MAC correto por tempo de resposta.
    if not hmac.compare_digest(hmac_cliente.encode(), esperado.encode()):
        enviar_mensagem(sessao.conn, "AUTH_FAIL BAD_MAC\n")
        fechar_conexao(sessao.conn)
        return

    sessao.autenticado = True
    sessao.proximo_seq = 1
    enviar_mensagem(sessao.conn, f"AUTH_OK {sessao.username}\n")
