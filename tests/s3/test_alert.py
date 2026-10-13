
import unittest

from s3.alert import Alerta


class TestAlerta(unittest.TestCase):

    def test_criar_alerta_valido(self):
        """Deve permitir criar um alerta válido."""

        alerta = Alerta(
            alerta_id="alerta-001",
            evento_id="evt-001",
            severidade="ALTA",
            destinatarios=["supervisor-01"],
            canais=["SOM", "TELA"]
        )

        alerta.validar()

        self.assertEqual(alerta.alerta_id, "alerta-001")
        self.assertEqual(alerta.evento_id, "evt-001")
        self.assertEqual(alerta.estado, "CRIADO")
        self.assertIsNotNone(alerta.criado_em)

    def test_alerta_sem_destinatarios(self):
        """Deve rejeitar um alerta sem destinatários."""

        alerta = Alerta(
            alerta_id="alerta-002",
            evento_id="evt-002",
            severidade="ALTA",
            destinatarios=[],
            canais=["SOM"]
        )

        with self.assertRaises(ValueError):
            alerta.validar()

    def test_alerta_sem_canais(self):
        """Deve rejeitar um alerta sem canais."""

        alerta = Alerta(
            alerta_id="alerta-003",
            evento_id="evt-003",
            severidade="MEDIA",
            destinatarios=["supervisor-01"],
            canais=[]
        )

        with self.assertRaises(ValueError):
            alerta.validar()


if __name__ == "__main__":
    unittest.main()