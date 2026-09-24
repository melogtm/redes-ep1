from __future__ import annotations

import socket
import threading
import time
from collections import deque
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Callable

from config_cliente import ConfigCliente
from modelos import EventoCliente, LoteCliente, StatusLote
from protocolo_cliente import (
    ErroProtocolo,
    LineBuffer,
    assinar,
    ler_mensagem,
    normalizar_preco,
    texto_assinado_lance,
    validar_nonce,
)


class ErroCliente(Exception):
    pass


class ErroAutenticacao(ErroCliente):
    pass


class ConexaoPerdida(ErroCliente):
    pass


class TimeoutResposta(ErroCliente):
    pass


class OperacaoRejeitada(ErroCliente):
    def __init__(self, operacao: str, motivo: str):
        super().__init__(f"{operacao} rejeitada: {motivo}")
        self.operacao = operacao
        self.motivo = motivo


class ResultadoLanceIndeterminado(ErroCliente):
    """O BID pode ter chegado ao servidor, mas a resposta foi perdida."""


class ClienteLeilao:
    """Cliente TCP completo para o protocolo do leilão.

    Existe somente uma thread lendo o socket.

    Essa decisão é importante porque a conexão mistura:
    - respostas de comandos iniciados pelo usuário;
    - KEEPALIVE;
    - PRICE_UPDATE;
    - TIME_UPDATE;
    - CLOSE.

    Se cada comando executasse recv() por conta própria, um recv() do BID
    poderia consumir, por exemplo, um PRICE_UPDATE pertencente ao mecanismo
    de push.
    """

    _RESPOSTAS = {
        "CHALLENGE",
        "AUTH_OK",
        "AUTH_FAIL",
        "LIST_BEGIN",
        "LOT",
        "LIST_END",
        "JOIN_OK",
        "JOIN_REJECTED",
        "BID_ACCEPTED",
        "BID_REJECTED",
    }

    def __init__(
        self,
        config: ConfigCliente,
        username: str,
        chave: str,
        ao_evento: Callable[[EventoCliente], None] | None = None,
    ) -> None:
        if not username or any(caractere.isspace() for caractere in username):
            raise ValueError("username deve ser um token sem espaços")

        if not chave:
            raise ValueError("chave não pode ser vazia")

        self.config = config
        self.username = username
        self._chave = chave

        self._ao_evento = ao_evento if ao_evento is not None else lambda evento: None

        # Protege troca/consulta do socket corrente.
        self._sock_lock = threading.RLock()

        # Nenhuma thread pode executar sendall simultaneamente.
        self._send_lock = threading.Lock()

        # O protocolo não tem IDs genéricos de requisição.
        # Serializar LIST/JOIN/BID simplifica a correlação de respostas.
        self._command_lock = threading.Lock()

        # Protege lote, seq, nonce e inscrições locais.
        self._state_lock = threading.RLock()

        self._sock: socket.socket | None = None

        self._connected = threading.Event()
        self._stop = threading.Event()

        self._reader_thread: threading.Thread | None = None
        self._keepalive_thread: threading.Thread | None = None

        # Respostas síncronas capturadas pela thread de recepção.
        # O número da geração evita usar resposta de uma conexão anterior.
        self._inbox_cv = threading.Condition()

        self._inbox: deque[tuple[int, list[str]]] = deque(maxlen=2048)

        # A geração muda sempre que uma nova sessão TCP/autenticada nasce.
        self._generation = 0

        # Challenge da sessão corrente.
        # O mesmo nonce participa da assinatura dos BID.
        self._nonce: str | None = None

        # AUTH_OK cria uma sessão cujo primeiro seq é 1.
        self._proximo_seq = 1

        self._lotes: dict[int, LoteCliente] = {}

        # JOINs que o usuário quer preservar mesmo depois de uma queda.
        self._joins_desejados: set[int] = set()

        # JOINs disparados automaticamente após uma reconexão.
        self._auto_joins_pendentes: set[int] = set()

    @property
    def conectado(self) -> bool:
        return self._connected.is_set()

    def conectar(self) -> None:
        """Abre TCP, autentica e inicia as threads de background."""

        if self._reader_thread is not None and self._reader_thread.is_alive():
            return

        sock, nonce = self._abrir_e_autenticar()

        self._instalar_socket(
            sock,
            nonce,
            reenviar_joins=False,
        )

        self._reader_thread = threading.Thread(
            target=self._loop_receber,
            name="leilao-receptor",
            daemon=True,
        )

        self._keepalive_thread = threading.Thread(
            target=self._loop_keepalive,
            name="leilao-keepalive",
            daemon=True,
        )

        self._reader_thread.start()
        self._keepalive_thread.start()

        self._emitir(
            "conectado",
            f"autenticado como {self.username}",
        )

    def encerrar(self) -> None:
        """Envia LOGOUT quando possível e fecha todos os recursos."""

        if self._stop.is_set():
            return

        self._stop.set()

        if self._connected.is_set():
            try:
                self._enviar_linha(
                    "LOGOUT",
                    aguardar_conexao=False,
                )
            except ErroCliente:
                pass

        self._marcar_desconectado(
            self._socket_atual(),
            emitir=False,
        )

        atual = threading.current_thread()

        for thread in (
            self._reader_thread,
            self._keepalive_thread,
        ):
            if thread is not None and thread.is_alive() and thread is not atual:
                thread.join(timeout=2.0)

        # Em Python não existe garantia de sobrescrever imediatamente
        # os bytes internos de uma string imutável, mas removemos a
        # referência do objeto assim que ele é encerrado.
        self._chave = ""

    def listar_lotes(
        self,
        apenas_ativos: bool = True,
    ) -> list[LoteCliente]:
        """Executa LIST e valida LIST_BEGIN/LOT/LIST_END."""

        with self._command_lock:
            geracao = self._enviar_linha("LIST")

            inicio = self._esperar(
                geracao,
                lambda p: bool(p) and p[0] == "LIST_BEGIN",
            )

            if len(inicio) != 2:
                raise ErroProtocolo("LIST_BEGIN malformado")

            try:
                quantidade_esperada = int(inicio[1])
            except ValueError as exc:
                raise ErroProtocolo("quantidade inválida em LIST_BEGIN") from exc

            if quantidade_esperada < 0:
                raise ErroProtocolo("LIST_BEGIN não pode anunciar quantidade negativa")

            recebidos: list[LoteCliente] = []

            while True:
                mensagem = self._esperar(
                    geracao,
                    lambda p: (
                        bool(p)
                        and p[0]
                        in {
                            "LOT",
                            "LIST_END",
                        }
                    ),
                )

                if mensagem[0] == "LIST_END":
                    break

                lote = self._parse_lot(mensagem)
                recebidos.append(lote)

            # O PROTOCOLO.md exige que a quantidade de LOT corresponda
            # ao número anunciado por LIST_BEGIN.
            if len(recebidos) != quantidade_esperada:
                raise ErroProtocolo(
                    "LIST_BEGIN anunciou "
                    f"{quantidade_esperada} lotes, "
                    f"mas foram recebidos {len(recebidos)}"
                )

            with self._state_lock:
                for lote in recebidos:
                    self._lotes[lote.id] = lote

            resultado = [replace(lote) for lote in recebidos]

            if apenas_ativos:
                resultado = [
                    lote for lote in resultado if lote.status is StatusLote.OPEN
                ]

            return resultado

    def entrar_lote(
        self,
        lote_id: int,
    ) -> LoteCliente:
        """Executa JOIN e registra a inscrição para futuras reconexões."""

        if lote_id < 0:
            raise ValueError("lote_id deve ser não negativo")

        # Guardamos a intenção antes do envio porque a conexão pode cair
        # exatamente depois de o servidor receber JOIN.
        with self._state_lock:
            self._joins_desejados.add(lote_id)

        with self._command_lock:
            geracao = self._enviar_linha(f"JOIN {lote_id}")

            resposta = self._esperar(
                geracao,
                lambda p: (
                    len(p) >= 2
                    and p[0]
                    in {
                        "JOIN_OK",
                        "JOIN_REJECTED",
                    }
                    and p[1] == str(lote_id)
                ),
            )

        if resposta[0] == "JOIN_REJECTED":
            motivo = resposta[2] if len(resposta) >= 3 else "RESPOSTA_MALFORMADA"

            with self._state_lock:
                self._joins_desejados.discard(lote_id)

            raise OperacaoRejeitada(
                "JOIN",
                motivo,
            )

        lote = self._parse_join_ok(resposta)

        with self._state_lock:
            self._lotes[lote.id] = lote

        return replace(lote)

    def enviar_lance(
        self,
        lote_id: int,
        preco: str | Decimal,
    ) -> LoteCliente:
        """Constrói, assina, envia BID e aguarda ACCEPTED/REJECTED."""

        preco_enviado = normalizar_preco(preco)

        with self._state_lock:
            if lote_id not in self._joins_desejados:
                raise ErroCliente("é necessário executar JOIN antes de enviar BID")

        with self._command_lock:
            geracao, seq = self._enviar_bid_assinado(
                lote_id,
                preco_enviado,
            )

            try:
                resposta = self._esperar(
                    geracao,
                    lambda p: (
                        len(p) >= 2
                        and p[0]
                        in {
                            "BID_ACCEPTED",
                            "BID_REJECTED",
                        }
                        and p[1] == str(lote_id)
                        and p[-1] == str(seq)
                    ),
                )

            except TimeoutResposta as exc:
                # O servidor pode ter aceitado o BID e a resposta ter se
                # perdido. Fechamos a sessão para que uma resposta atrasada
                # com o mesmo seq não seja confundida com outro BID.
                self._marcar_desconectado(self._socket_atual())

                raise ResultadoLanceIndeterminado(
                    "o BID foi enviado, mas a resposta não chegou "
                    "no prazo; a sessão será refeita e o lance "
                    "não será repetido automaticamente"
                ) from exc

            except ConexaoPerdida as exc:
                raise ResultadoLanceIndeterminado(
                    "a conexão foi perdida após o envio do BID; "
                    "o cliente não repetirá o lance automaticamente"
                ) from exc

        if resposta[0] == "BID_REJECTED":
            motivo = resposta[2] if len(resposta) >= 4 else "RESPOSTA_MALFORMADA"

            # Seq NÃO avança em rejeição.
            raise OperacaoRejeitada(
                "BID",
                motivo,
            )

        if len(resposta) != 5:
            raise ErroProtocolo("BID_ACCEPTED malformado")

        try:
            preco_aceito = Decimal(resposta[2])

            tempo_fim = int(resposta[3])

        except (
            InvalidOperation,
            ValueError,
        ) as exc:
            raise ErroProtocolo("BID_ACCEPTED contém valores inválidos") from exc

        with self._state_lock:
            # Somente um BID aceito incrementa seq.
            #
            # Se uma reconexão já ocorreu, a NOVA sessão começa
            # novamente em seq = 1, então não podemos incrementá-la
            # com base na resposta da sessão antiga.
            if self._generation == geracao:
                self._proximo_seq = seq + 1

            lote = self._lotes.get(lote_id)

            if lote is None:
                lote = LoteCliente(
                    id=lote_id,
                    descricao="",
                    status=StatusLote.OPEN,
                    preco_atual=preco_aceito,
                    tempo_fim=tempo_fim,
                )

                self._lotes[lote_id] = lote

            else:
                lote.preco_atual = preco_aceito
                lote.tempo_fim = tempo_fim

            return replace(lote)

    def snapshot_lotes(
        self,
    ) -> list[LoteCliente]:
        """Devolve cópias do estado local conhecido."""

        with self._state_lock:
            return [replace(lote) for lote in self._lotes.values()]

    # ------------------------------------------------------------------
    # Conexão e autenticação
    # ------------------------------------------------------------------

    def _abrir_e_autenticar(
        self,
    ) -> tuple[socket.socket, str]:
        """Abre uma nova sessão TCP e completa LOGIN/AUTH."""

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
        )

        try:
            sock.settimeout(self.config.timeout_conexao)

            sock.connect(
                (
                    self.config.host,
                    self.config.porta,
                )
            )

            sock.settimeout(self.config.timeout_resposta)

            buffer = LineBuffer(self.config.tamanho_maximo_linha)

            # Etapa 1: LOGIN
            sock.sendall((f"LOGIN {self.username}\n").encode("utf-8"))

            partes = ler_mensagem(
                self._receber_linha_sincrona(
                    sock,
                    buffer,
                )
            )

            if partes and partes[0] == "AUTH_FAIL":
                motivo = partes[1] if len(partes) > 1 else "DESCONHECIDO"

                raise ErroAutenticacao(f"LOGIN recusado: {motivo}")

            if len(partes) != 2 or partes[0] != "CHALLENGE":
                raise ErroProtocolo("esperado CHALLENGE após LOGIN")

            nonce = partes[1]
            validar_nonce(nonce)

            # Etapa 2: HMAC-SHA256(chave, nonce)
            mac = assinar(
                self._chave,
                nonce,
            )

            sock.sendall((f"AUTH {mac}\n").encode("utf-8"))

            partes = ler_mensagem(
                self._receber_linha_sincrona(
                    sock,
                    buffer,
                )
            )

            if partes and partes[0] == "AUTH_FAIL":
                motivo = partes[1] if len(partes) > 1 else "DESCONHECIDO"

                raise ErroAutenticacao(f"AUTH recusado: {motivo}")

            if len(partes) != 2 or partes[0] != "AUTH_OK":
                raise ErroProtocolo("esperado AUTH_OK após AUTH")

            if partes[1] != self.username:
                raise ErroProtocolo("AUTH_OK retornou username inesperado")

            # Timeout curto apenas para que a thread de recepção
            # consiga verificar periodicamente _stop.
            # KEEPALIVE mantém o servidor ativo.
            sock.settimeout(1.0)

            return sock, nonce

        except Exception:
            try:
                sock.close()
            except OSError:
                pass

            raise

    def _receber_linha_sincrona(
        self,
        sock: socket.socket,
        buffer: LineBuffer,
    ) -> str:
        """Recebe uma linha durante o pequeno handshake inicial."""

        fim = time.monotonic() + self.config.timeout_resposta

        while True:
            restante = fim - time.monotonic()

            if restante <= 0:
                raise TimeoutResposta("timeout durante autenticação")

            sock.settimeout(restante)

            try:
                data = sock.recv(self.config.tamanho_recv)

            except socket.timeout as exc:
                raise TimeoutResposta("timeout durante autenticação") from exc

            if not data:
                raise ConexaoPerdida("servidor fechou a conexão durante autenticação")

            linhas = buffer.feed(data)

            if linhas:
                return linhas[0]

    def _instalar_socket(
        self,
        sock: socket.socket,
        nonce: str,
        reenviar_joins: bool,
    ) -> None:
        """Instala uma sessão autenticada.

        Em reconexão, JOINs anteriores são enviados antes de liberar
        _connected. Assim um BID novo não ultrapassa os JOINs dentro
        do fluxo TCP.
        """

        with (
            self._sock_lock,
            self._state_lock,
        ):
            self._sock = sock
            self._nonce = nonce

            # AUTH_OK => seq recomeça em 1.
            self._proximo_seq = 1

            self._generation += 1
            geracao = self._generation

            joins = sorted(self._joins_desejados) if reenviar_joins else []

            self._auto_joins_pendentes = set(joins)

        try:
            with self._send_lock:
                for lote_id in joins:
                    sock.sendall((f"JOIN {lote_id}\n").encode("utf-8"))

        except OSError as exc:
            self._marcar_desconectado(sock)

            raise ConexaoPerdida("falha ao restaurar inscrições") from exc

        self._connected.set()

        with self._inbox_cv:
            self._inbox_cv.notify_all()

        if reenviar_joins:
            self._emitir(
                "reconectado",
                (f"sessão {geracao} autenticada; {len(joins)} JOIN(s) reenviado(s)"),
            )

    def _socket_atual(
        self,
    ) -> socket.socket | None:
        with self._sock_lock:
            return self._sock

    def _enviar_linha(
        self,
        linha: str,
        aguardar_conexao: bool = True,
    ) -> int:
        """Envia uma linha textual completa.

        Retorna a geração da sessão pela qual a mensagem saiu.
        """

        if "\n" in linha or "\r" in linha:
            raise ValueError("linha de protocolo não pode conter CR/LF")

        if aguardar_conexao:
            if not self._connected.wait(self.config.timeout_conexao):
                raise ConexaoPerdida("cliente não está conectado")

        elif not self._connected.is_set():
            raise ConexaoPerdida("cliente não está conectado")

        with self._send_lock:
            with self._sock_lock:
                sock = self._sock
                geracao = self._generation

            if sock is None:
                raise ConexaoPerdida("socket indisponível")

            try:
                sock.sendall((linha + "\n").encode("utf-8"))

                return geracao

            except OSError as exc:
                self._marcar_desconectado(sock)

                raise ConexaoPerdida("falha ao enviar dados") from exc

    def _enviar_bid_assinado(
        self,
        lote_id: int,
        preco_enviado: str,
    ) -> tuple[int, int]:
        """Obtém nonce/seq atomicamente e envia BID assinado."""

        if not self._connected.wait(self.config.timeout_conexao):
            raise ConexaoPerdida("cliente não está conectado")

        with self._send_lock:
            with (
                self._sock_lock,
                self._state_lock,
            ):
                sock = self._sock
                geracao = self._generation
                nonce = self._nonce
                seq = self._proximo_seq

            if sock is None or nonce is None:
                raise ConexaoPerdida("sessão autenticada indisponível")

            texto = texto_assinado_lance(
                lote_id,
                preco_enviado,
                seq,
                nonce,
            )

            mac = assinar(
                self._chave,
                texto,
            )

            linha = f"BID {lote_id} {preco_enviado} {seq} {mac}\n"

            try:
                sock.sendall(linha.encode("utf-8"))

            except OSError as exc:
                self._marcar_desconectado(sock)

                # Como sendall falhou depois de iniciada a operação,
                # não podemos provar se zero, parte ou todos os bytes
                # chegaram ao outro lado.
                raise ResultadoLanceIndeterminado(
                    "falha de transporte durante o envio do BID"
                ) from exc

        return geracao, seq

    # ------------------------------------------------------------------
    # Thread receptora, keepalive e reconexão
    # ------------------------------------------------------------------

    def _loop_receber(self) -> None:
        """Único consumidor de recv() depois da autenticação."""

        buffer = LineBuffer(self.config.tamanho_maximo_linha)

        while not self._stop.is_set():
            if not self._connected.is_set():
                if not self._reconectar():
                    return

                # Nova conexão = novo fluxo TCP.
                buffer = LineBuffer(self.config.tamanho_maximo_linha)

            sock = self._socket_atual()

            if sock is None:
                self._connected.clear()
                continue

            try:
                data = sock.recv(self.config.tamanho_recv)

                if not data:
                    raise ConexaoPerdida("servidor fechou a conexão")

                linhas = buffer.feed(data)

                for linha in linhas:
                    partes = ler_mensagem(linha)

                    if partes:
                        self._tratar_mensagem(partes)

            except socket.timeout:
                # Timeout local de 1 segundo.
                # Não significa falha do servidor.
                continue

            except (
                OSError,
                ConexaoPerdida,
                ErroProtocolo,
            ) as exc:
                if not self._stop.is_set():
                    self._emitir(
                        "desconectado",
                        str(exc),
                    )

                self._marcar_desconectado(
                    sock,
                    emitir=False,
                )

                buffer = LineBuffer(self.config.tamanho_maximo_linha)

    def _reconectar(self) -> bool:
        """Reconecta com backoff exponencial limitado."""

        atraso = self.config.atraso_reconexao_inicial

        while not self._stop.is_set():
            self._emitir(
                "reconectando",
                (f"tentando reconectar em {atraso:.1f}s"),
            )

            if self._stop.wait(atraso):
                return False

            try:
                sock, nonce = self._abrir_e_autenticar()

                self._instalar_socket(
                    sock,
                    nonce,
                    reenviar_joins=True,
                )

                return True

            except (
                OSError,
                ErroCliente,
                ErroProtocolo,
            ) as exc:
                self._emitir(
                    "reconexao_falhou",
                    str(exc),
                )

                atraso = min(
                    atraso * 2,
                    self.config.atraso_reconexao_maximo,
                )

        return False

    def _loop_keepalive(self) -> None:
        """Mantém tráfego abaixo do timeout de 40 s do servidor."""

        while not self._stop.wait(self.config.intervalo_keepalive):
            if not self._connected.is_set():
                continue

            try:
                self._enviar_linha("KEEPALIVE")

            except ErroCliente:
                # A thread de recepção detectará ou já detectou
                # a queda e executará a reconexão.
                pass

    def _marcar_desconectado(
        self,
        sock_esperado: socket.socket | None,
        emitir: bool = True,
    ) -> None:
        """Fecha somente se o socket ainda for o socket corrente.

        Isso evita que um erro atrasado da sessão anterior derrube uma nova
        conexão que já tenha sido instalada.
        """

        if sock_esperado is None:
            return

        fechar: socket.socket | None = None

        with self._sock_lock:
            if self._sock is sock_esperado:
                fechar = self._sock
                self._sock = None

                self._connected.clear()

        if fechar is not None:
            try:
                fechar.close()
            except OSError:
                pass

            with self._inbox_cv:
                self._inbox_cv.notify_all()

            if emitir:
                self._emitir(
                    "desconectado",
                    "conexão TCP perdida",
                )

    # ------------------------------------------------------------------
    # Despacho das mensagens recebidas
    # ------------------------------------------------------------------

    def _tratar_mensagem(
        self,
        partes: list[str],
    ) -> None:
        comando = partes[0]

        if comando == "KEEPALIVE":
            return

        if comando == "PRICE_UPDATE":
            self._tratar_price_update(partes)
            return

        if comando == "TIME_UPDATE":
            self._tratar_time_update(partes)
            return

        if comando == "CLOSE":
            self._tratar_close(partes)
            return

        # JOINs executados automaticamente durante reconexão não devem ficar
        # no inbox como se fossem resposta a um JOIN digitado posteriormente.
        if (
            comando
            in {
                "JOIN_OK",
                "JOIN_REJECTED",
            }
            and len(partes) >= 2
        ):
            try:
                lote_id = int(partes[1])
            except ValueError:
                lote_id = -1

            with self._state_lock:
                automatico = lote_id in self._auto_joins_pendentes

                if automatico:
                    self._auto_joins_pendentes.discard(lote_id)

            if automatico:
                if comando == "JOIN_OK":
                    lote = self._parse_join_ok(partes)

                    with self._state_lock:
                        self._lotes[lote.id] = lote

                    self._emitir(
                        "reinscrito",
                        (f"JOIN restaurado para o lote {lote.id}"),
                        lote_id=lote.id,
                    )

                else:
                    motivo = partes[2] if len(partes) >= 3 else "DESCONHECIDO"

                    with self._state_lock:
                        self._joins_desejados.discard(lote_id)

                    self._emitir(
                        "reinscricao_falhou",
                        (f"JOIN {lote_id} recusado após reconexão: {motivo}"),
                        lote_id=lote_id,
                    )

                return

        if comando in self._RESPOSTAS:
            with self._sock_lock:
                geracao = self._generation

            with self._inbox_cv:
                self._inbox.append(
                    (
                        geracao,
                        partes,
                    )
                )

                self._inbox_cv.notify_all()

            return

        # Compatibilidade futura não é presumida:
        # comando desconhecido é ignorado e informado à interface.
        self._emitir(
            "protocolo",
            (f"mensagem desconhecida ignorada: {comando}"),
        )

    def _esperar(
        self,
        geracao: int,
        predicado: Callable[
            [list[str]],
            bool,
        ],
    ) -> list[str]:
        """Aguarda uma resposta específica da sessão indicada."""

        fim = time.monotonic() + self.config.timeout_resposta

        with self._inbox_cv:
            while True:
                for indice, (
                    gen,
                    partes,
                ) in enumerate(self._inbox):
                    if gen == geracao and predicado(partes):
                        # deque não fornece pop(indice).
                        # Rotate remove apenas o item encontrado
                        # sem destruir a ordem dos demais.
                        self._inbox.rotate(-indice)

                        _, resposta = self._inbox.popleft()

                        self._inbox.rotate(indice)

                        return resposta

                with self._sock_lock:
                    geracao_atual = self._generation

                if geracao_atual != geracao or not self._connected.is_set():
                    raise ConexaoPerdida(
                        "a conexão mudou enquanto a resposta era aguardada"
                    )

                restante = fim - time.monotonic()

                if restante <= 0:
                    raise TimeoutResposta("servidor não respondeu dentro do prazo")

                self._inbox_cv.wait(restante)

    # ------------------------------------------------------------------
    # Parsers das mensagens do leilão
    # ------------------------------------------------------------------

    def _parse_lot(
        self,
        partes: list[str],
    ) -> LoteCliente:
        if len(partes) != 6 or partes[0] != "LOT":
            raise ErroProtocolo("LOT malformado")

        return self._montar_lote(
            partes[1],
            partes[2],
            partes[3],
            partes[4],
            partes[5],
        )

    def _parse_join_ok(
        self,
        partes: list[str],
    ) -> LoteCliente:
        if len(partes) != 6 or partes[0] != "JOIN_OK":
            raise ErroProtocolo("JOIN_OK malformado")

        return self._montar_lote(
            partes[1],
            partes[2],
            partes[3],
            partes[4],
            partes[5],
        )

    def _montar_lote(
        self,
        id_s: str,
        status_s: str,
        preco_s: str,
        epoch_s: str,
        descricao: str,
    ) -> LoteCliente:
        try:
            lote_id = int(id_s)
            status = StatusLote(status_s)
            preco = Decimal(preco_s)
            epoch = int(epoch_s)

        except (
            ValueError,
            InvalidOperation,
        ) as exc:
            raise ErroProtocolo("dados de lote inválidos") from exc

        if lote_id < 0 or not preco.is_finite() or preco < 0:
            raise ErroProtocolo("dados de lote fora da faixa válida")

        return LoteCliente(
            id=lote_id,
            descricao=descricao,
            status=status,
            preco_atual=preco,
            tempo_fim=epoch,
        )

    def _tratar_price_update(
        self,
        partes: list[str],
    ) -> None:
        """Aceita a documentação e a implementação real enviada.

        PROTOCOLO.md:

            PRICE_UPDATE <id> <price> :<username>

        utils.py do servidor:

            PRICE_UPDATE <id> <price> <epoch> :<username>
        """

        if len(partes) not in {
            4,
            5,
        }:
            raise ErroProtocolo("PRICE_UPDATE malformado")

        try:
            lote_id = int(partes[1])

            preco = Decimal(partes[2])

            if len(partes) == 5:
                epoch: int | None = int(partes[3])
                usuario = partes[4]

            else:
                epoch = None
                usuario = partes[3]

        except (
            ValueError,
            InvalidOperation,
        ) as exc:
            raise ErroProtocolo("PRICE_UPDATE contém valores inválidos") from exc

        if not preco.is_finite() or preco < 0:
            raise ErroProtocolo("PRICE_UPDATE contém preço inválido")

        with self._state_lock:
            lote = self._lotes.get(lote_id)

            if lote is not None:
                lote.preco_atual = preco
                lote.lider_atual = usuario

                # O servidor real já inclui epoch no PRICE_UPDATE.
                if epoch is not None:
                    lote.tempo_fim = epoch

        self._emitir(
            "preco",
            (f"lote {lote_id}: novo preço {preco:.2f} por {usuario}"),
            lote_id=lote_id,
            preco=preco,
            tempo_fim=epoch,
            usuario=usuario,
        )

    def _tratar_time_update(
        self,
        partes: list[str],
    ) -> None:
        if len(partes) != 3:
            raise ErroProtocolo("TIME_UPDATE malformado")

        try:
            lote_id = int(partes[1])

            epoch = int(partes[2])

        except ValueError as exc:
            raise ErroProtocolo("TIME_UPDATE contém valores inválidos") from exc

        with self._state_lock:
            lote = self._lotes.get(lote_id)

            if lote is not None:
                lote.tempo_fim = epoch

        self._emitir(
            "tempo",
            (f"lote {lote_id}: término atualizado para epoch {epoch}"),
            lote_id=lote_id,
            tempo_fim=epoch,
        )

    def _tratar_close(
        self,
        partes: list[str],
    ) -> None:
        if len(partes) != 4:
            raise ErroProtocolo("CLOSE malformado")

        try:
            lote_id = int(partes[1])

            preco = Decimal(partes[2])

        except (
            ValueError,
            InvalidOperation,
        ) as exc:
            raise ErroProtocolo("CLOSE contém valores inválidos") from exc

        if not preco.is_finite() or preco < 0:
            raise ErroProtocolo("CLOSE contém preço inválido")

        vencedor = partes[3]

        with self._state_lock:
            lote = self._lotes.get(lote_id)

            if lote is not None:
                lote.preco_atual = preco
                lote.status = StatusLote.CLOSED

                lote.lider_atual = None if vencedor == "NONE" else vencedor

        self._emitir(
            "fechado",
            (f"lote {lote_id} fechado em {preco:.2f}; vencedor: {vencedor}"),
            lote_id=lote_id,
            preco=preco,
            usuario=vencedor,
        )

    def _emitir(
        self,
        tipo: str,
        mensagem: str,
        lote_id: int | None = None,
        preco: Decimal | None = None,
        tempo_fim: int | None = None,
        usuario: str | None = None,
    ) -> None:
        """Notifica a interface sem permitir que ela derrube a rede."""

        try:
            self._ao_evento(
                EventoCliente(
                    tipo=tipo,
                    mensagem=mensagem,
                    lote_id=lote_id,
                    preco=preco,
                    tempo_fim=tempo_fim,
                    usuario=usuario,
                )
            )

        except Exception:
            # Erros de impressão/UI não podem matar a thread receptora.
            pass
