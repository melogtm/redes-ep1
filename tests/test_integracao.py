"""Testes de integração: um servidor de verdade e mensagens cruas pelo socket.

Cobrem o que o cliente oficial não gera, como AUTH e BID repetidos ou
forjados. Cada teste sobe o seu próprio servidor, com lotes zerados.
"""

import hashlib
import hmac
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import contexto

from server.utils.utils import carregar_chaves

CHAVES = carregar_chaves(str(contexto.CHAVES))

# Lote 1 dura o bastante para qualquer teste; o lote 2 fecha logo.
LOTES = "1 | Lote longo | 100.00 | 1200\n2 | Lote curto | 10.00 | 2\n"


def mac(chave, texto):
    return hmac.new(chave.encode(), texto.encode(), hashlib.sha256).hexdigest()


def porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ClienteCru:
    """Fala o protocolo linha a linha, sem nenhuma das proteções do cliente."""

    def __init__(self, porta):
        self.sock = socket.create_connection(("127.0.0.1", porta), timeout=5)
        self.buf = b""
        self.nonce = None

    def enviar(self, linha):
        self.sock.sendall((linha + "\n").encode())

    def receber(self):
        while b"\n" not in self.buf:
            dados = self.sock.recv(4096)
            if not dados:
                raise ConnectionError("o servidor fechou a conexão")
            self.buf += dados
        linha, self.buf = self.buf.split(b"\n", 1)
        return linha.decode()

    def esperar(self, prefixo):
        """Descarta notificações até chegar a linha com o prefixo."""
        while True:
            linha = self.receber()
            if linha.startswith(prefixo):
                return linha

    def foi_fechado(self):
        try:
            return self.sock.recv(4096) == b""
        except ConnectionError:  # no Windows, reset ou abort em vez de FIN
            return True

    def autenticar(self, usuario="alice"):
        """Faz LOGIN e AUTH e devolve a linha AUTH enviada."""
        self.enviar(f"LOGIN {usuario}")
        self.nonce = self.esperar("CHALLENGE").split()[1]
        linha_auth = f"AUTH {mac(CHAVES[usuario], self.nonce)}"
        self.enviar(linha_auth)
        self.esperar(f"AUTH_OK {usuario}")
        return linha_auth

    def linha_bid(self, lote, preco, seq, usuario="alice"):
        texto = f"LANCE {lote} {preco} {seq} {self.nonce}"
        return f"BID {lote} {preco} {seq} {mac(CHAVES[usuario], texto)}"

    def fechar(self):
        self.sock.close()


class TestIntegracao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        lotes = Path(self.tmp.name) / "lots.conf"
        lotes.write_text(LOTES, encoding="utf-8")

        self.porta = porta_livre()
        self.servidor = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "server.server",
                "--port",
                str(self.porta),
                "--lots",
                str(lotes),
            ],
            cwd=contexto.SRC,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.clientes = []

        limite = time.monotonic() + 5
        while True:
            try:
                socket.create_connection(("127.0.0.1", self.porta), timeout=1).close()
                break
            except OSError:
                if time.monotonic() > limite:
                    self.fail("o servidor não subiu em 5 s")
                time.sleep(0.05)

    def tearDown(self):
        for cliente in self.clientes:
            cliente.fechar()
        self.servidor.terminate()
        self.servidor.wait(timeout=5)
        self.tmp.cleanup()

    def cliente(self):
        c = ClienteCru(self.porta)
        self.clientes.append(c)
        return c

    # ------------------------------------------------------------ autenticação

    def test_comando_antes_do_login_e_ignorado(self):
        c = self.cliente()
        c.enviar("LIST")
        c.enviar("LOGIN alice")
        self.assertTrue(c.receber().startswith("CHALLENGE "))

    def test_cada_login_recebe_um_nonce_diferente(self):
        nonces = set()
        for _ in range(5):
            c = self.cliente()
            c.autenticar()
            nonces.add(c.nonce)
        self.assertEqual(len(nonces), 5)

    def test_auth_repetido_na_mesma_sessao(self):
        c = self.cliente()
        linha_auth = c.autenticar()
        c.enviar(linha_auth)
        self.assertEqual(c.receber(), "AUTH_FAIL NONCE_EXPIRED")
        self.assertTrue(c.foi_fechado())

    def test_auth_capturado_nao_serve_em_outra_sessao(self):
        a = self.cliente()
        linha_auth = a.autenticar()

        b = self.cliente()
        b.enviar("LOGIN alice")
        b.esperar("CHALLENGE")
        b.enviar(linha_auth)
        self.assertEqual(b.receber(), "AUTH_FAIL BAD_MAC")
        self.assertTrue(b.foi_fechado())

    def test_auth_com_chave_errada(self):
        c = self.cliente()
        c.enviar("LOGIN alice")
        nonce = c.esperar("CHALLENGE").split()[1]
        c.enviar(f"AUTH {mac('chave-errada', nonce)}")
        self.assertEqual(c.receber(), "AUTH_FAIL BAD_MAC")
        self.assertTrue(c.foi_fechado())

    def test_usuario_desconhecido(self):
        c = self.cliente()
        c.enviar("LOGIN mallory")
        self.assertEqual(c.receber(), "AUTH_FAIL UNKNOWN_USER")
        self.assertTrue(c.foi_fechado())

    # ------------------------------------------------------------------ lances

    def test_bid_repetido_e_recusado_pelo_seq(self):
        c = self.cliente()
        c.autenticar()
        c.enviar("JOIN 1")
        c.esperar("JOIN_OK 1")
        linha = c.linha_bid(1, "150.00", 1)
        c.enviar(linha)
        self.assertTrue(c.esperar("BID_").startswith("BID_ACCEPTED 1 150.00"))
        c.enviar(linha)
        self.assertEqual(c.esperar("BID_"), "BID_REJECTED 1 BAD_SEQ 1")

    def test_bid_com_mac_forjado(self):
        c = self.cliente()
        c.autenticar()
        c.enviar("JOIN 1")
        c.esperar("JOIN_OK 1")
        c.enviar("BID 1 150.00 1 " + "0" * 64)
        self.assertEqual(c.esperar("BID_"), "BID_REJECTED 1 BAD_MAC 1")

    def test_bid_de_outra_sessao_nao_vale(self):
        a = self.cliente()
        a.autenticar()
        linha = a.linha_bid(1, "150.00", 1)  # assinado com o nonce de a

        b = self.cliente()
        b.autenticar()
        b.enviar("JOIN 1")
        b.esperar("JOIN_OK 1")
        b.enviar(linha)
        self.assertEqual(b.esperar("BID_"), "BID_REJECTED 1 BAD_MAC 1")

    def test_bid_sem_join(self):
        c = self.cliente()
        c.autenticar()
        c.enviar(c.linha_bid(1, "150.00", 1))
        self.assertEqual(c.esperar("BID_"), "BID_REJECTED 1 NOT_JOINED 1")

    def test_bid_em_lote_inexistente(self):
        c = self.cliente()
        c.autenticar()
        c.enviar(c.linha_bid(99, "150.00", 1))
        self.assertEqual(c.esperar("BID_"), "BID_REJECTED 99 NO_SUCH_LOT 1")

    def test_lote_fecha_sem_lances_e_recusa_lance_depois(self):
        c = self.cliente()
        c.autenticar()
        c.enviar("JOIN 2")
        c.esperar("JOIN_OK 2")
        self.assertEqual(c.esperar("CLOSE 2"), "CLOSE 2 10.00 :NONE")
        c.enviar(c.linha_bid(2, "20.00", 1))
        self.assertEqual(c.esperar("BID_"), "BID_REJECTED 2 CLOSED 1")

    def test_lance_e_notificado_a_outro_inscrito(self):
        alice = self.cliente()
        alice.autenticar("alice")
        alice.enviar("JOIN 1")
        alice.esperar("JOIN_OK 1")

        bob = self.cliente()
        bob.autenticar("bob")
        bob.enviar("JOIN 1")
        bob.esperar("JOIN_OK 1")
        bob.enviar(bob.linha_bid(1, "150.00", 1, usuario="bob"))
        fim = bob.esperar("BID_ACCEPTED").split()[3]

        self.assertEqual(alice.receber(), f"PRICE_UPDATE 1 150.00 {fim} :bob")
        self.assertEqual(alice.receber(), f"TIME_UPDATE 1 {fim}")

    # -------------------------------------------------------------------- TCP

    def test_mensagem_partida_em_dois_envios(self):
        c = self.cliente()
        c.sock.sendall(b"LOG")
        time.sleep(0.2)
        c.sock.sendall(b"IN alice\n")
        self.assertTrue(c.receber().startswith("CHALLENGE "))

    def test_duas_mensagens_num_envio(self):
        c = self.cliente()
        c.autenticar()
        c.sock.sendall(b"JOIN 1\nLIST\n")
        self.assertTrue(c.receber().startswith("JOIN_OK 1 OPEN"))
        self.assertEqual(c.receber(), "LIST_BEGIN 2")


if __name__ == "__main__":
    unittest.main()
