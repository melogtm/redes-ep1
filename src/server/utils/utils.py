import hmac
import logging
import socket
import time

from server.enum.lote_status import LoteStatus
from server.model.lote import Lote
from server.model.sessao import Sessao
from server.utils.protocolo import assinar_bytes, assinar_lance_string

IDENTIFICADOR_COMENTARIO = "#"
JANELA_DE_TEMPO_SEGUNDOS = 10
TEMPO_MONITORAMENTO_SEGUNDOS = 1

log = logging.getLogger("servidor")


def hora(epoch: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(epoch))


def nomes(inscritos: list) -> str:
    return ", ".join(sorted(username for _, username in inscritos))


def carregar_chaves(caminho: str) -> dict:
    chaves = {}

    with open(caminho, "r", encoding="utf-8") as arquivo:
        for linha in arquivo:
            linha = linha.strip()

            if not linha or linha.startswith(IDENTIFICADOR_COMENTARIO):
                continue

            partes = linha.split()

            if len(partes) >= 2:
                chaves[partes[0]] = partes[1]

    return chaves


def carregar_lotes(caminho: str) -> dict:
    lotes = {}

    with open(caminho, "r", encoding="utf-8") as arquivo:
        for linha in arquivo:
            linha = linha.strip()

            if not linha or linha.startswith(IDENTIFICADOR_COMENTARIO):
                continue

            parts = [p.strip() for p in linha.split("|")]

            if len(parts) >= 4:
                lote_id = int(parts[0])
                descricao = parts[1]
                preco_inicio = float(parts[2])
                duracao_segundos = int(parts[3])

                lotes[lote_id] = Lote(
                    lote_id, descricao, preco_inicio, duracao_segundos
                )

    return lotes


def enviar_mensagem(conn: socket.socket, mensagem: str) -> None:
    if log.isEnabledFor(logging.DEBUG):
        try:
            ip, porta = conn.getpeername()[:2]
            destino = f"{ip}:{porta}"
        except OSError:
            destino = "?"
        log.debug("-> %s: %s", destino, mensagem.rstrip("\n"))

    try:
        conn.send(mensagem.encode())
    except OSError:
        pass


def fechar_conexao(conn: socket.socket) -> None:
    try:
        conn.close()
    except OSError:
        pass


def comando_listar(sessao: Sessao, lotes: dict) -> None:
    enviar_mensagem(sessao.conn, f"LIST_BEGIN {len(lotes)}\n")

    for lote in lotes.values():
        enviar_mensagem(
            sessao.conn,
            f"LOT {lote.id} {lote.status.name} {lote.preco_atual:.2f} "
            f"{int(lote.tempo_fim)} :{lote.descricao}\n",
        )

    enviar_mensagem(sessao.conn, "LIST_END\n")


def comando_entrar(sessao: Sessao, partes: list, lotes: dict) -> None:

    if len(partes) < 2:
        enviar_mensagem(sessao.conn, "JOIN_REJECTED -1 BAD_REQUEST\n")
        return

    try:
        lote_id = int(partes[1])
    except ValueError:
        enviar_mensagem(sessao.conn, "JOIN_REJECTED -1 BAD_REQUEST\n")
        return

    if lote_id not in lotes:
        log.info("%s: JOIN %d -> JOIN_REJECTED UNKNOWN_LOTE", sessao, lote_id)
        enviar_mensagem(sessao.conn, f"JOIN_REJECTED {lote_id} UNKNOWN_LOTE\n")
        return

    lote = lotes[lote_id]

    # O estado do lote e a lista de inscritos são compartilhados com o monitor.
    with lote.lock:
        sessao.lotes_inscritos.add(lote_id)
        lote.inscritos.add((sessao.conn, sessao.username))

        status = lote.status.name
        preco = lote.preco_atual
        desc = lote.descricao
        epoch = int(lote.tempo_fim)

    log.info(
        "%s: JOIN %d -> JOIN_OK (%s, R$ %.2f, fecha às %s)",
        sessao,
        lote_id,
        status,
        preco,
        hora(epoch),
    )
    enviar_mensagem(
        sessao.conn, f"JOIN_OK {lote_id} {status} {preco:.2f} {epoch} :{desc}\n"
    )


def rejeitar_lance(sessao: Sessao, lote_id: int, motivo: str, seq: int) -> None:
    log.info("%s: BID no lote %d -> BID_REJECTED %s", sessao, lote_id, motivo)
    enviar_mensagem(sessao.conn, f"BID_REJECTED {lote_id} {motivo} {seq}\n")


def comando_lance(sessao: Sessao, partes: list, lotes: dict, chaves: dict) -> None:
    if len(partes) < 5:
        log.info("%s: BID malformado ignorado", sessao)
        return

    try:
        lote_id = int(partes[1])
    except ValueError:
        log.info("%s: BID malformado ignorado", sessao)
        return

    preco_do_lance = partes[2]
    seq_str = partes[3]
    client_hmac = partes[4]

    try:
        preco_lance = float(preco_do_lance)
        seq = int(seq_str)
    except ValueError:
        log.info("%s: BID malformado ignorado", sessao)
        return

    if lote_id not in lotes:
        rejeitar_lance(sessao, lote_id, "NO_SUCH_LOT", seq)
        return

    if lote_id not in sessao.lotes_inscritos:
        rejeitar_lance(sessao, lote_id, "NOT_JOINED", seq)
        return

    if seq != sessao.proximo_seq:
        rejeitar_lance(sessao, lote_id, "BAD_SEQ", seq)
        return

    lance_string_assinada = assinar_lance_string(
        str(lote_id), str(preco_do_lance), str(seq_str), str(sessao.nonce)
    )

    chave_do_client = chaves.get(sessao.username, "")

    esperado = assinar_bytes(chave_do_client.encode(), lance_string_assinada.encode())

    if not hmac.compare_digest(client_hmac.encode(), esperado.encode()):
        rejeitar_lance(sessao, lote_id, "BAD_MAC", seq)
        return

    lote = lotes[lote_id]

    with lote.lock:
        if lote.status != LoteStatus.OPEN:
            rejeitar_lance(sessao, lote_id, "CLOSED", seq)
            return

        if preco_lance <= lote.preco_atual:
            rejeitar_lance(sessao, lote_id, "LOW_BID", seq)
            return

        sessao.proximo_seq += 1
        tempo_fim_anterior = lote.tempo_fim
        lote.lider_atual = sessao.username
        lote.preco_atual = preco_lance

        agora = time.time()

        # Um lance nos últimos 10 segundos estende o leilão para evitar um
        # encerramento abrupto.
        prorrogado = tempo_fim_anterior - agora < JANELA_DE_TEMPO_SEGUNDOS
        if prorrogado:
            lote.tempo_fim = agora + JANELA_DE_TEMPO_SEGUNDOS

        inscritos_para_notificar = list(lote.inscritos)

        log.info(
            "%s: BID no lote %d a R$ %.2f (seq %d) -> BID_ACCEPTED; fim %s%s",
            sessao,
            lote_id,
            preco_lance,
            seq,
            hora(lote.tempo_fim),
            f" (soft close: faltavam {tempo_fim_anterior - agora:.1f} s)"
            if prorrogado
            else "",
        )

        enviar_mensagem(
            sessao.conn,
            f"BID_ACCEPTED {lote_id} {preco_lance:.2f} {int(lote.tempo_fim)} {seq}\n",
        )

        for conn, _ in inscritos_para_notificar:
            enviar_mensagem(
                conn,
                f"PRICE_UPDATE {lote_id} {preco_lance:.2f} "
                f"{int(lote.tempo_fim)} :{sessao.username}\n",
            )

        for conn, _ in inscritos_para_notificar:
            enviar_mensagem(conn, f"TIME_UPDATE {lote_id} {int(lote.tempo_fim)}\n")

        log.info(
            "lote %d: PRICE_UPDATE e TIME_UPDATE para [%s]",
            lote_id,
            nomes(inscritos_para_notificar),
        )


def monitorar_lote_fechamento(lotes: dict) -> None:
    while True:
        # A frequência define a precisão máxima do fechamento automático.
        time.sleep(TEMPO_MONITORAMENTO_SEGUNDOS)
        for lote in lotes.values():
            if lote.status != LoteStatus.OPEN:
                continue
            with lote.lock:
                if time.time() < lote.tempo_fim:
                    continue

                lote.status = LoteStatus.CLOSED

                if lote.lider_atual:
                    ganhador, preco = lote.lider_atual, lote.preco_atual
                else:
                    ganhador, preco = "NONE", lote.preco_atual

                inscritos_para_notificar = list(lote.inscritos)

            log.info(
                "lote %d fechado: vencedor %s, R$ %.2f; CLOSE para [%s]",
                lote.id,
                ganhador,
                preco,
                nomes(inscritos_para_notificar),
            )

            for conn, _ in inscritos_para_notificar:
                enviar_mensagem(conn, f"CLOSE {lote.id} {preco:.2f} :{ganhador}\n")
