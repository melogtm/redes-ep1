from __future__ import annotations

import argparse
import getpass
import threading
from datetime import datetime
from pathlib import Path

from cliente_leilao import (
    ClienteLeilao,
    ErroCliente,
    OperacaoRejeitada,
    ResultadoLanceIndeterminado,
)
from config_cliente import ConfigCliente
from modelos import EventoCliente, LoteCliente
from protocolo_cliente import ErroProtocolo


# Pushes chegam por uma thread diferente daquela que lê input().
# O lock evita que duas threads imprimam ao mesmo tempo.
_PRINT_LOCK = threading.Lock()


def imprimir(texto: str = "") -> None:
    with _PRINT_LOCK:
        print(
            texto,
            flush=True,
        )


def carregar_chave(
    caminho: Path,
    username: str,
) -> str:
    """Lê o mesmo formato de arquivo empregado pelo servidor.

    Formato aceito:

        # comentário
        alice segredo_da_alice
        bob segredo_do_bob
    """

    with caminho.open(
        "r",
        encoding="utf-8",
    ) as arquivo:

        for linha in arquivo:
            linha = linha.strip()

            if (
                not linha
                or linha.startswith("#")
            ):
                continue

            partes = linha.split()

            if (
                len(partes) >= 2
                and partes[0] == username
            ):
                return partes[1]

    raise ValueError(
        f"usuário {username!r} "
        f"não encontrado em {caminho}"
    )


def formatar_lote(
    lote: LoteCliente,
) -> str:
    fim = (
        datetime
        .fromtimestamp(lote.tempo_fim)
        .astimezone()
        .strftime(
            "%Y-%m-%d %H:%M:%S %z"
        )
    )

    lider = (
        lote.lider_atual
        if lote.lider_atual is not None
        else "-"
    )

    return (
        f"[{lote.id}] "
        f"{lote.status.value} | "
        f"R$ {lote.preco_atual:.2f} | "
        f"fim: {fim} | "
        f"restante: "
        f"{lote.segundos_restantes()}s | "
        f"líder: {lider} | "
        f"{lote.descricao}"
    )


def ao_evento(
    evento: EventoCliente,
) -> None:
    # PRICE_UPDATE, TIME_UPDATE, CLOSE e eventos de reconexão aparecem
    # imediatamente, mesmo enquanto o usuário está no menu.
    imprimir(
        f"\n[PUSH/{evento.tipo}] "
        f"{evento.mensagem}"
    )


def mostrar_ajuda() -> None:
    imprimir(
        "Comandos:\n"
        "  list                 lista apenas lotes OPEN\n"
        "  list all             lista todos os lotes retornados pelo servidor\n"
        "  join <id>            entra no lote e começa a receber seus pushes\n"
        "  bid <id> <preço>     envia um lance, ex.: bid 1 150.00\n"
        "  show                 mostra o estado local conhecido dos lotes\n"
        "  help                 mostra esta ajuda\n"
        "  quit                 envia LOGOUT e encerra"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Cliente do projeto de leilão online"
        )
    )

    # HOST e PORT são obrigatórios porque esses valores não aparecem
    # nos arquivos do servidor fornecidos.
    parser.add_argument(
        "--host",
        required=True,
        help="host/IP do servidor",
    )

    parser.add_argument(
        "--port",
        required=True,
        type=int,
        help="porta TCP do servidor",
    )

    parser.add_argument(
        "--username",
        required=True,
        help=(
            "usuário cadastrado "
            "no arquivo de chaves do servidor"
        ),
    )

    parser.add_argument(
        "--key-file",
        type=Path,
        help=(
            "arquivo opcional no formato "
            "'usuario chave'; "
            "se omitido, a chave é lida "
            "sem eco pelo terminal"
        ),
    )

    args = parser.parse_args()

    try:
        if args.key_file is not None:
            chave = carregar_chave(
                args.key_file,
                args.username,
            )

        else:
            # Não colocar a chave em --key reduz a exposição do segredo
            # no histórico do shell e na lista de processos.
            chave = getpass.getpass(
                "Chave HMAC: "
            )

        config = ConfigCliente(
            host=args.host,
            porta=args.port,
        )

        cliente = ClienteLeilao(
            config=config,
            username=args.username,
            chave=chave,
            ao_evento=ao_evento,
        )

        cliente.conectar()

    except (
        OSError,
        ValueError,
        ErroCliente,
        ErroProtocolo,
    ) as exc:
        imprimir(
            f"Erro ao iniciar: {exc}"
        )

        return 1

    try:
        imprimir(
            "Conectado e autenticado."
        )

        # Já mostra os lotes ativos ao entrar no programa.
        try:
            lotes = cliente.listar_lotes(
                apenas_ativos=True
            )

            imprimir(
                "Lotes ativos:"
            )

            if not lotes:
                imprimir(
                    "  (nenhum lote OPEN)"
                )

            for lote in lotes:
                imprimir(
                    "  "
                    + formatar_lote(lote)
                )

        except (
            ErroCliente,
            ErroProtocolo,
        ) as exc:
            imprimir(
                "Não foi possível obter "
                f"a lista inicial: {exc}"
            )

        mostrar_ajuda()

        while True:

            try:
                entrada = input(
                    "leilao> "
                ).strip()

            except EOFError:
                entrada = "quit"

            if not entrada:
                continue

            partes = entrada.split()
            comando = partes[0].lower()

            try:
                # ------------------------------------------------------
                # QUIT
                # ------------------------------------------------------
                if comando in {
                    "quit",
                    "exit",
                    "logout",
                }:
                    break

                # ------------------------------------------------------
                # HELP
                # ------------------------------------------------------
                if comando == "help":
                    mostrar_ajuda()
                    continue

                # ------------------------------------------------------
                # LIST
                # ------------------------------------------------------
                if comando == "list":

                    if (
                        len(partes) > 2
                        or (
                            len(partes) == 2
                            and partes[1].lower()
                            != "all"
                        )
                    ):
                        imprimir(
                            "uso: list [all]"
                        )
                        continue

                    apenas_ativos = (
                        len(partes) == 1
                    )

                    lotes = cliente.listar_lotes(
                        apenas_ativos=apenas_ativos
                    )

                    if not lotes:
                        imprimir(
                            "(nenhum lote)"
                        )

                    for lote in lotes:
                        imprimir(
                            formatar_lote(lote)
                        )

                    continue

                # ------------------------------------------------------
                # JOIN
                # ------------------------------------------------------
                if comando == "join":

                    if len(partes) != 2:
                        imprimir(
                            "uso: join <id>"
                        )
                        continue

                    lote_id = int(
                        partes[1]
                    )

                    lote = cliente.entrar_lote(
                        lote_id
                    )

                    imprimir(
                        "Inscrito: "
                        + formatar_lote(lote)
                    )

                    continue

                # ------------------------------------------------------
                # BID
                # ------------------------------------------------------
                if comando == "bid":

                    if len(partes) != 3:
                        imprimir(
                            "uso: bid <id> <preço>"
                        )
                        continue

                    lote_id = int(
                        partes[1]
                    )

                    preco = partes[2]

                    lote = cliente.enviar_lance(
                        lote_id,
                        preco,
                    )

                    imprimir(
                        "Lance aceito: "
                        + formatar_lote(lote)
                    )

                    continue

                # ------------------------------------------------------
                # SHOW
                # ------------------------------------------------------
                if comando == "show":

                    lotes = sorted(
                        cliente.snapshot_lotes(),
                        key=lambda lote: lote.id,
                    )

                    if not lotes:
                        imprimir(
                            "(sem estado local de lotes)"
                        )

                    for lote in lotes:
                        imprimir(
                            formatar_lote(lote)
                        )

                    continue

                imprimir(
                    "comando desconhecido; "
                    "use 'help'"
                )

            except ResultadoLanceIndeterminado as exc:
                imprimir(
                    f"ATENÇÃO: {exc}"
                )

            except OperacaoRejeitada as exc:
                imprimir(
                    str(exc)
                )

            except (
                ErroCliente,
                ErroProtocolo,
                ValueError,
            ) as exc:
                imprimir(
                    f"Erro: {exc}"
                )

    except KeyboardInterrupt:
        imprimir(
            "\nInterrompido pelo usuário."
        )

    finally:
        cliente.encerrar()

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
