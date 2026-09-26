"""Testes unitários da regra do lance, sem rede e sem esperar o relógio."""

import time
import unittest

import contexto  # noqa: F401

from server.model.lote import Lote
from server.model.sessao import Sessao
from server.utils.protocolo import assinar_bytes, assinar_lance_string
from server.utils.utils import JANELA_DE_TEMPO_SEGUNDOS, comando_lance

CHAVE = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
NONCE = "0123456789abcdef0123456789abcdef"


class ConexaoFalsa:
    """Guarda o que o servidor enviaria pelo socket."""

    def __init__(self):
        self.enviadas = []

    def send(self, dados):
        self.enviadas.append(dados.decode())
        return len(dados)

    def getpeername(self):
        return ("127.0.0.1", 50000)


class TestLance(unittest.TestCase):
    def setUp(self):
        self.conn = ConexaoFalsa()
        self.sessao = Sessao(self.conn, ("127.0.0.1", 50000))
        self.sessao.username = "alice"
        self.sessao.autenticado = True
        self.sessao.nonce = NONCE
        self.sessao.lotes_inscritos.add(1)

        self.lote = Lote(1, "Lote de teste", 100.0, 1200)
        self.lote.inscritos.add((self.conn, "alice"))
        self.lotes = {1: self.lote}

    def lance(self, preco, seq):
        texto = assinar_lance_string("1", preco, str(seq), NONCE)
        mac = assinar_bytes(CHAVE.encode(), texto.encode())
        self.conn.enviadas.clear()
        comando_lance(
            self.sessao,
            ["BID", "1", preco, str(seq), mac],
            self.lotes,
            {"alice": CHAVE},
        )
        return self.conn.enviadas

    def test_lance_aceito_notifica_o_proprio_autor(self):
        enviadas = self.lance("150.00", 1)
        self.assertTrue(enviadas[0].startswith("BID_ACCEPTED 1 150.00"))
        self.assertTrue(enviadas[1].startswith("PRICE_UPDATE 1 150.00"))
        self.assertTrue(enviadas[1].endswith(":alice\n"))
        self.assertTrue(enviadas[2].startswith("TIME_UPDATE 1"))
        self.assertEqual(self.lote.lider_atual, "alice")

    def test_lance_igual_ao_atual_e_recusado(self):
        enviadas = self.lance("100.00", 1)
        self.assertEqual(enviadas, ["BID_REJECTED 1 LOW_BID 1\n"])

    def test_seq_so_avanca_quando_o_lance_e_aceito(self):
        self.lance("90.00", 1)  # LOW_BID
        self.assertEqual(self.sessao.proximo_seq, 1)
        self.lance("150.00", 1)  # aceito
        self.assertEqual(self.sessao.proximo_seq, 2)

    def test_lance_longe_do_fim_nao_prorroga(self):
        fim = time.time() + 38
        self.lote.tempo_fim = fim
        self.lance("150.00", 1)
        self.assertEqual(self.lote.tempo_fim, fim)

    def test_lance_nos_ultimos_10_s_prorroga_para_chegada_mais_10(self):
        self.lote.tempo_fim = time.time() + 9.9
        antes = time.time()
        self.lance("150.00", 1)
        depois = time.time()
        self.assertGreaterEqual(self.lote.tempo_fim, antes + JANELA_DE_TEMPO_SEGUNDOS)
        self.assertLessEqual(self.lote.tempo_fim, depois + JANELA_DE_TEMPO_SEGUNDOS)


if __name__ == "__main__":
    unittest.main()
