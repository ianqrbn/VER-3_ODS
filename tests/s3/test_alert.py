import unittest
from datetime import datetime

from s3.alert import Alerta
from s3.errors import INVALID_CHANNEL, INVALID_RECIPIENT, ErroS3


class TestAlerta(unittest.TestCase):

    def alerta(self, **alteracoes):
        dados = dict(
            alerta_id="alerta-001",
            severidade="HIGH",
            destinatarios=["role:supervisor"],
            canais=["SCREEN"],
            titulo="EPI ausente: luva",
            mensagem="Pessoa sem luva",
            evento_id="evt-001",
        )
        dados.update(alteracoes)
        return Alerta(**dados)

    def test_criar_alerta_valido(self):
        """Deve permitir criar um alerta válido."""

        alerta = self.alerta()
        alerta.validar()

        self.assertEqual(alerta.estado, "CREATED")
        self.assertIsNotNone(alerta.criado_em.tzinfo)

    def test_evento_opcional(self):
        """Alerta de negócio não tem event_id."""

        self.alerta(evento_id=None).validar()

    def test_alerta_sem_destinatarios(self):
        with self.assertRaises(ErroS3) as contexto:
            self.alerta(destinatarios=[]).validar()

        self.assertEqual(contexto.exception.codigo, INVALID_RECIPIENT)

    def test_destinatario_sem_prefixo(self):
        """Destinatário precisa ser user:, group: ou role:."""

        for valor in ("supervisor-01", "user:", "papel:x"):
            with self.subTest(valor=valor):
                with self.assertRaises(ErroS3):
                    self.alerta(destinatarios=[valor]).validar()

    def test_destinatarios_como_texto(self):
        """Um texto solto não vira lista de letras."""

        with self.assertRaises(ErroS3) as contexto:
            self.alerta(destinatarios="role:supervisor").validar()

        self.assertEqual(contexto.exception.codigo, INVALID_RECIPIENT)

    def test_alerta_sem_canais(self):
        with self.assertRaises(ErroS3) as contexto:
            self.alerta(canais=[]).validar()

        self.assertEqual(contexto.exception.codigo, INVALID_CHANNEL)

    def test_canal_desconhecido(self):
        """Os canais antigos em português não são mais aceitos."""

        with self.assertRaises(ErroS3):
            self.alerta(canais=["TELA"]).validar()

    def test_severidade_e_estado_invalidos(self):
        with self.assertRaises(ErroS3):
            self.alerta(severidade="ALTA").validar()

        with self.assertRaises(ErroS3):
            self.alerta(estado="CRIADO").validar()

    def test_titulo_vazio(self):
        with self.assertRaises(ErroS3):
            self.alerta(titulo=" ").validar()

    def test_horario_sem_fuso(self):
        with self.assertRaises(ErroS3):
            self.alerta(criado_em=datetime(2026, 9, 23)).validar()


if __name__ == "__main__":
    unittest.main()
