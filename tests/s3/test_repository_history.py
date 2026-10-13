
import unittest

from s3.alert import Alerta
from s3.history import RegistroHistorico
from s3.repository import AlertRepository


class TestRepositoryHistory(unittest.TestCase):

    def setUp(self):
        """Prepara um repositório com um alerta salvo."""

        self.repository = AlertRepository()

        self.alerta = Alerta(
            alerta_id="alerta-001",
            evento_id="evt-001",
            severidade="ALTA",
            destinatarios=["supervisor-01"],
            canais=["SOM", "TELA"]
        )

        self.repository.salvar(self.alerta)

    def test_historico_criado_automaticamente(self):
        """Salvar um alerta deve registrar sua criação."""

        historico = self.repository.buscar_historico(
            "alerta-001"
        )

        self.assertEqual(len(historico), 1)

        self.assertEqual(
            historico[0].acao,
            "CRIADO"
        )

        self.assertEqual(
            historico[0].evento_id,
            "evt-001"
        )

    def test_registrar_reconhecimento(self):
        """Deve permitir adicionar um reconhecimento."""

        registro = RegistroHistorico(
            alerta_id="alerta-001",
            evento_id="evt-001",
            acao="RECONHECIDO",
            autor_id="supervisor-01"
        )

        self.repository.registrar_historico(registro)

        historico = self.repository.buscar_historico(
            "alerta-001"
        )

        self.assertEqual(len(historico), 2)

        self.assertEqual(
            historico[1].acao,
            "RECONHECIDO"
        )

        self.assertEqual(
            historico[1].autor_id,
            "supervisor-01"
        )

    def test_rejeitar_evento_incorreto(self):
        """O evento do registro deve pertencer ao alerta."""

        registro = RegistroHistorico(
            alerta_id="alerta-001",
            evento_id="evt-999",
            acao="RECONHECIDO",
            autor_id="supervisor-01"
        )

        with self.assertRaises(ValueError):
            self.repository.registrar_historico(registro)

        historico = self.repository.buscar_historico(
            "alerta-001"
        )

        self.assertEqual(len(historico), 1)

    def test_rejeitar_alerta_inexistente(self):
        """Não deve registrar ações em alertas inexistentes."""

        registro = RegistroHistorico(
            alerta_id="alerta-999",
            evento_id="evt-999",
            acao="RECONHECIDO",
            autor_id="supervisor-01"
        )

        with self.assertRaises(ValueError):
            self.repository.registrar_historico(registro)

    def test_rejeitar_registro_duplicado(self):
        """Não deve adicionar duas vezes o mesmo registro."""

        registro = RegistroHistorico(
            alerta_id="alerta-001",
            evento_id="evt-001",
            acao="RECONHECIDO",
            autor_id="supervisor-01"
        )

        self.repository.registrar_historico(registro)

        with self.assertRaises(ValueError):
            self.repository.registrar_historico(registro)

        historico = self.repository.buscar_historico(
            "alerta-001"
        )

        self.assertEqual(len(historico), 2)

    def test_rejeitar_criacao_manual(self):
        """O registro CRIADO deve ser automático."""

        registro = RegistroHistorico(
            alerta_id="alerta-001",
            evento_id="evt-001",
            acao="CRIADO"
        )

        with self.assertRaises(ValueError):
            self.repository.registrar_historico(registro)

        historico = self.repository.buscar_historico(
            "alerta-001"
        )

        self.assertEqual(len(historico), 1)


if __name__ == "__main__":
    unittest.main()