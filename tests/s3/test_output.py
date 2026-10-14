
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from s3.alert import Alerta
from s3.output import (
    alerta_para_json,
    formatar_horario,
    serializar_alerta,
)

ARQUIVO_SAIDA = (
    Path(__file__).resolve().parents[2] / "jsons" / "saida.json"
)


class TestSaidaAlerta(unittest.TestCase):

    def setUp(self):
        """Reproduz o alerta de jsons/saida.json."""

        self.alerta = Alerta(
            alerta_id="alerta-001",
            evento_id="evt-001",
            severidade="ALTA",
            destinatarios=["operador-01"],
            canais=["TELA", "SOM"],
            evidencia_ref="evidencia-001",
            criado_em=datetime(
                2026, 10, 1, 18, 0, 0, tzinfo=timezone.utc
            ),
        )

        self.publicado_em = datetime(
            2026, 10, 1, 18, 0, 5, tzinfo=timezone.utc
        )

    def test_igual_ao_exemplo_documentado(self):
        """A saída deve reproduzir jsons/saida.json."""

        with open(ARQUIVO_SAIDA, encoding="utf-8") as arquivo:
            esperado = json.load(arquivo)

        envelope = serializar_alerta(
            self.alerta,
            publicado_em=self.publicado_em,
        )

        self.assertEqual(envelope, esperado)

    def test_json_valido(self):
        """O texto gerado deve ser JSON decodificável."""

        texto = alerta_para_json(
            self.alerta,
            publicado_em=self.publicado_em,
        )

        dados = json.loads(texto)

        self.assertEqual(dados["producer"], "S3")
        self.assertEqual(
            dados["payload"]["alerta_id"],
            "alerta-001"
        )

    def test_estado_atual_do_alerta(self):
        """A saída deve refletir o estado atual."""

        self.alerta.estado = "RECONHECIDO"

        envelope = serializar_alerta(self.alerta)

        self.assertEqual(
            envelope["payload"]["estado"],
            "RECONHECIDO"
        )

    def test_evidencia_ausente(self):
        """Sem evidência, o campo deve ser null."""

        self.alerta.evidencia_ref = None

        dados = json.loads(alerta_para_json(self.alerta))

        self.assertIsNone(dados["payload"]["evidencia_ref"])

    def test_alerta_invalido(self):
        """Não deve serializar alerta inválido."""

        self.alerta.destinatarios = []

        with self.assertRaises(ValueError):
            serializar_alerta(self.alerta)

    def test_horario_convertido_para_utc(self):
        """Horários com outro fuso devem sair em UTC."""

        brasilia = timezone(timedelta(hours=-3))
        horario = datetime(2026, 10, 1, 15, 0, 0, tzinfo=brasilia)

        self.assertEqual(
            formatar_horario(horario),
            "2026-10-01T18:00:00Z"
        )

    def test_horario_sem_fuso(self):
        """Horário sem fuso deve ser rejeitado."""

        with self.assertRaises(ValueError):
            formatar_horario(datetime(2026, 10, 1, 18, 0, 0))

    def test_listas_sao_copiadas(self):
        """Alterar o envelope não deve alterar o alerta."""

        envelope = serializar_alerta(self.alerta)
        envelope["payload"]["canais"].append("PUSH")

        self.assertEqual(self.alerta.canais, ["TELA", "SOM"])


if __name__ == "__main__":
    unittest.main()
