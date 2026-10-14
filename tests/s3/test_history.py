
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime

from s3.history import RegistroHistorico

from fabricas import FUTURO


class TestRegistroHistorico(unittest.TestCase):

    def test_criar_registro_valido(self):
        """Deve criar um registro de criação válido."""

        registro = RegistroHistorico(alerta_id="alerta-001", acao="CREATED")

        self.assertIsNone(registro.autor_id)
        self.assertTrue(registro.registro_id)
        self.assertIsNotNone(registro.registrado_em.tzinfo)

    def test_reconhecimento_valido(self):
        """Deve aceitar reconhecimento com autor e motivo."""

        registro = RegistroHistorico(
            alerta_id="alerta-001",
            acao="ACKNOWLEDGED",
            autor_id="user:maria",
            motivo="verificado",
        )

        self.assertEqual(registro.autor_id, "user:maria")
        self.assertEqual(registro.motivo, "verificado")

    def test_rejeitar_acao_invalida(self):
        """Deve rejeitar ações desconhecidas."""

        for acao in ("RECONHECIDO", "DELETED"):
            with self.subTest(acao=acao):
                with self.assertRaises(ValueError):
                    RegistroHistorico(
                        alerta_id="alerta-001", acao=acao, autor_id="user:x"
                    )

    def test_rejeitar_acao_sem_autor(self):
        """Ações manuais devem identificar o autor, inclusive sem espaços."""

        for autor in (None, "", "   "):
            with self.subTest(autor=autor):
                with self.assertRaises(ValueError):
                    RegistroHistorico(
                        alerta_id="alerta-001",
                        acao="CLOSED",
                        autor_id=autor,
                    )

    def test_silenciamento_exige_prazo(self):
        """MUTED precisa de mute_until."""

        with self.assertRaises(ValueError):
            RegistroHistorico(
                alerta_id="alerta-001", acao="MUTED", autor_id="user:x"
            )

        RegistroHistorico(
            alerta_id="alerta-001",
            acao="MUTED",
            autor_id="user:x",
            silenciado_ate=FUTURO,
        )

    def test_impedir_alteracao(self):
        """Um registro criado não deve ser alterado."""

        registro = RegistroHistorico(alerta_id="alerta-001", acao="CREATED")

        with self.assertRaises(FrozenInstanceError):
            registro.acao = "CLOSED"

    def test_rejeitar_horario_sem_fuso(self):
        """O horário precisa conter informação de fuso."""

        with self.assertRaises(ValueError):
            RegistroHistorico(
                alerta_id="alerta-001",
                acao="CREATED",
                registrado_em=datetime(2026, 9, 23),
            )


if __name__ == "__main__":
    unittest.main()
