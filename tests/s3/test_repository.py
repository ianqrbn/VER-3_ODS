
import unittest

from s3.alert import Alerta
from s3.repository import AlertRepository


class TestAlertRepository(unittest.TestCase):

    def setUp(self):
        """Cria um repositório vazio para cada teste."""

        self.repository = AlertRepository()

        self.alerta = Alerta(
            alerta_id="alerta-001",
            evento_id="evt-001",
            severidade="ALTA",
            destinatarios=["supervisor-01"],
            canais=["SOM", "TELA"]
        )

    def test_salvar_alerta(self):
        """Deve armazenar um alerta válido."""

        self.repository.salvar(self.alerta)

        resultado = self.repository.buscar_por_id(
            "alerta-001"
        )

        self.assertEqual(resultado, self.alerta)

    def test_buscar_por_evento(self):
        """Deve localizar o alerta pelo evento de origem."""

        self.repository.salvar(self.alerta)

        resultado = self.repository.buscar_por_evento(
            "evt-001"
        )

        self.assertEqual(resultado, self.alerta)

    def test_rejeitar_id_duplicado(self):
        """Não deve permitir dois alertas com o mesmo ID."""

        self.repository.salvar(self.alerta)

        outro_alerta = Alerta(
            alerta_id="alerta-001",
            evento_id="evt-002",
            severidade="MEDIA",
            destinatarios=["supervisor-02"],
            canais=["TELA"]
        )

        with self.assertRaises(ValueError):
            self.repository.salvar(outro_alerta)

    def test_rejeitar_evento_duplicado(self):
        """Não deve permitir dois alertas para o mesmo evento."""

        self.repository.salvar(self.alerta)

        outro_alerta = Alerta(
            alerta_id="alerta-002",
            evento_id="evt-001",
            severidade="ALTA",
            destinatarios=["supervisor-01"],
            canais=["SOM"]
        )

        with self.assertRaises(ValueError):
            self.repository.salvar(outro_alerta)

    def test_buscar_alerta_inexistente(self):
        """Uma busca sem resultado deve retornar None."""

        resultado = self.repository.buscar_por_id(
            "alerta-inexistente"
        )

        self.assertIsNone(resultado)


if __name__ == "__main__":
    unittest.main()