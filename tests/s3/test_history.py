
import unittest

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from s3.history import RegistroHistorico


class TestRegistroHistorico(unittest.TestCase):

    def test_criar_registro_valido(self):
        """Deve criar um registro de criação válido."""

        registro = RegistroHistorico(
            alerta_id="alerta-001",
            evento_id="evt-001",
            acao="CRIADO"
        )

        self.assertEqual(registro.acao, "CRIADO")
        self.assertEqual(registro.alerta_id, "alerta-001")
        self.assertIsNotNone(registro.registro_id)

        self.assertIsNotNone(
            registro.registrado_em.tzinfo
        )

    def test_reconhecimento_valido(self):
        """Deve aceitar reconhecimento com autor."""

        registro = RegistroHistorico(
            alerta_id="alerta-001",
            evento_id="evt-001",
            acao="RECONHECIDO",
            autor_id="supervisor-01"
        )

        self.assertEqual(
            registro.autor_id,
            "supervisor-01"
        )

        self.assertEqual(
            registro.acao,
            "RECONHECIDO"
        )

    def test_rejeitar_acao_invalida(self):
        """Deve rejeitar ações desconhecidas."""

        with self.assertRaises(ValueError):
            RegistroHistorico(
                alerta_id="alerta-001",
                evento_id="evt-001",
                acao="APAGADO"
            )

    def test_rejeitar_acao_sem_autor(self):
        """Reconhecimento deve identificar o autor."""

        with self.assertRaises(ValueError):
            RegistroHistorico(
                alerta_id="alerta-001",
                evento_id="evt-001",
                acao="RECONHECIDO"
            )

    def test_impedir_alteracao(self):
        """Um registro criado não deve ser alterado."""

        registro = RegistroHistorico(
            alerta_id="alerta-001",
            evento_id="evt-001",
            acao="CRIADO"
        )

        with self.assertRaises(FrozenInstanceError):
            registro.acao = "ENCERRADO"

    def test_rejeitar_horario_sem_fuso(self):
        """O horário precisa conter informação de fuso."""

        horario = datetime(2026, 9, 18, 10, 0, 0)

        with self.assertRaises(ValueError):
            RegistroHistorico(
                alerta_id="alerta-001",
                evento_id="evt-001",
                acao="CRIADO",
                registrado_em=horario
            )


if __name__ == "__main__":
    unittest.main()