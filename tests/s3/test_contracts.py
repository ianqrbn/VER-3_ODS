
import unittest

from s3.contracts import EventoQualificado


class TestEventoQualificado(unittest.TestCase):

    def test_evento_valido(self):
        """Um evento válido deve ser aceito."""

        evento = EventoQualificado(
            evento_id="evt-001",
            tipo="VIOLACAO_EPI",
            origem="S2",
            timestamp="2026-09-18T10:00:00Z",
            confianca=0.96,
            pessoa_id="pessoa-37",
            zona_id="producao",
            evidencia_ref="evidencia-001"
        )

        evento.validar()

        self.assertEqual(evento.evento_id, "evt-001")
        self.assertEqual(evento.confianca, 0.96)

    def test_confianca_invalida(self):
        """Uma confiança acima de 1 deve ser rejeitada."""

        evento = EventoQualificado(
            evento_id="evt-002",
            tipo="VIOLACAO_EPI",
            origem="S2",
            timestamp="2026-09-18T10:00:00Z",
            confianca=1.5
        )

        with self.assertRaises(ValueError):
            evento.validar()


if __name__ == "__main__":
    unittest.main()