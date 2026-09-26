"""Testes unitários do framing, do parser, dos preços e do HMAC."""

import unittest

import contexto  # noqa: F401
import protocolo_cliente as cli

from server.utils import protocolo as srv


class TestLineBufferServidor(unittest.TestCase):
    def test_varias_mensagens_numa_leitura(self):
        buf = srv.LineBuffer()
        self.assertEqual(buf.feed(b"LIST\nJOIN 1\n"), ["LIST", "JOIN 1"])

    def test_mensagem_dividida_em_duas_leituras(self):
        buf = srv.LineBuffer()
        self.assertEqual(buf.feed(b"LOG"), [])
        self.assertEqual(buf.feed(b"IN alice\nLI"), ["LOGIN alice"])
        self.assertEqual(buf.feed(b"ST\n"), ["LIST"])

    def test_linhas_vazias_sao_descartadas(self):
        buf = srv.LineBuffer()
        self.assertEqual(buf.feed(b"\n\nLIST\n\n"), ["LIST"])


class TestLineBufferCliente(unittest.TestCase):
    def test_linha_maior_que_o_limite(self):
        buf = cli.LineBuffer(tamanho_maximo_linha=16)
        with self.assertRaises(cli.ErroProtocolo):
            buf.feed(b"x" * 17)


class TestLerMensagem(unittest.TestCase):
    def test_campo_final_com_espacos(self):
        linha = "LOT 2 OPEN 50.00 1790448485 :Lote longo com espaços"
        esperado = ["LOT", "2", "OPEN", "50.00", "1790448485", "Lote longo com espaços"]
        self.assertEqual(srv.ler_mensagem(linha), esperado)
        self.assertEqual(cli.ler_mensagem(linha), esperado)

    def test_comando_sem_argumentos(self):
        self.assertEqual(srv.ler_mensagem("LIST"), ["LIST"])

    def test_linha_em_branco(self):
        self.assertEqual(srv.ler_mensagem("   "), [])


class TestPreco(unittest.TestCase):
    def test_completa_duas_casas(self):
        self.assertEqual(cli.normalizar_preco("150"), "150.00")
        self.assertEqual(cli.normalizar_preco("150.5"), "150.50")

    def test_recusa_mais_de_duas_casas(self):
        # O cliente não arredonda: o texto do preço entra na assinatura.
        with self.assertRaises(ValueError):
            cli.normalizar_preco("60.001")

    def test_recusa_zero_negativo_e_texto(self):
        for valor in ("0", "-1", "abc", "inf"):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                cli.normalizar_preco(valor)


class TestAssinatura(unittest.TestCase):
    def test_cliente_e_servidor_assinam_o_mesmo_texto(self):
        nonce = "0123456789abcdef0123456789abcdef"
        texto_cli = cli.texto_assinado_lance(2, "75.00", 1, nonce)
        texto_srv = srv.assinar_lance_string("2", "75.00", "1", nonce)
        self.assertEqual(texto_cli, texto_srv)

        chave = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
        self.assertEqual(
            cli.assinar(chave, texto_cli),
            srv.assinar_bytes(chave.encode(), texto_srv.encode()),
        )


if __name__ == "__main__":
    unittest.main()
