
import json
import unittest
from datetime import datetime, timezone

from s3.alert import Alerta
from s3.ingestion import IngestorEventos
from s3.output import alerta_para_json, payload_alerta, serializar_alerta
from s3.routing import RoteadorAlertas
from s3.service import AlertService

from fabricas import FUTURO, ler_json, texto_json


class TestSaidaAlerta(unittest.TestCase):

    def setUp(self):
        self.alerta = Alerta(
            alerta_id="alerta-001",
            severidade="HIGH",
            destinatarios=["role:supervisor"],
            canais=["SCREEN"],
            titulo="EPI ausente: luva",
            mensagem="Pessoa sem luva",
            evento_id="evt-001",
            criado_em=datetime(2026, 9, 23, 14, 30, 0, 500000, tzinfo=timezone.utc),
        )

    def test_igual_ao_exemplo_documentado(self):
        """jsons/entrada.json + routing_a5.json produzem jsons/saida.json."""

        roteador = RoteadorAlertas.de_artefato(
            ler_json("routing_a5.json"), "routing-a5-1"
        )
        alerta = IngestorEventos(
            AlertService(roteador=roteador)
        ).receber(texto_json("entrada.json"))

        alerta.alerta_id = "0f1e2d3c-4b5a-4968-8776-655443322110"
        alerta.criado_em = datetime(
            2026, 9, 23, 14, 30, 0, 500000, tzinfo=timezone.utc
        )

        envelope = serializar_alerta(
            alerta,
            sequence=0,
            publicado_em=datetime(
                2026, 9, 23, 14, 30, 0, 520000, tzinfo=timezone.utc
            ),
            message_id="2e3f4a5b-6c7d-4e8f-9a0b-1c2d3e4f5a6b",
        )

        self.assertEqual(envelope, ler_json("saida.json"))

    def test_envelope_ev_servico(self):
        envelope = serializar_alerta(self.alerta, sequence=7)

        self.assertEqual(envelope["schema"], "ods.s3.alert")
        self.assertEqual(envelope["message_type"], "event")
        self.assertEqual(envelope["producer"], "S3")
        self.assertEqual(envelope["sequence"], 7)
        # Sem evento de origem, captured_at = criação.
        self.assertEqual(envelope["captured_at"], "2026-09-23T14:30:00.500Z")

    def test_opcionais_omitidos(self):
        payload = payload_alerta(self.alerta)

        for campo in (
            "clip_id", "acknowledged_by", "acknowledged_at",
            "muted_until", "closed_by", "closed_at",
        ):
            self.assertNotIn(campo, payload)

    def test_dados_do_ciclo_de_vida(self):
        """Quem reconheceu, até quando silenciou e quem encerrou."""

        self.alerta.estado = "CLOSED"
        self.alerta.reconhecido_por = "user:maria"
        self.alerta.reconhecido_em = datetime(2026, 9, 23, 14, 30, 41, tzinfo=timezone.utc)
        self.alerta.silenciado_ate = FUTURO
        self.alerta.encerrado_por = "user:joao"
        self.alerta.encerrado_em = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)

        payload = payload_alerta(self.alerta)

        self.assertEqual(payload["state"], "CLOSED")
        self.assertEqual(payload["acknowledged_by"], "user:maria")
        self.assertEqual(payload["acknowledged_at"], "2026-09-23T14:30:41.000Z")
        self.assertEqual(payload["muted_until"], "2030-01-01T00:00:00.000Z")
        self.assertEqual(payload["closed_by"], "user:joao")

    def test_json_valido(self):
        dados = json.loads(alerta_para_json(self.alerta))

        self.assertEqual(dados["payload"]["alert_id"], "alerta-001")

    def test_alerta_invalido(self):
        self.alerta.destinatarios = []

        with self.assertRaises(ValueError):
            serializar_alerta(self.alerta)

    def test_listas_sao_copiadas(self):
        payload = payload_alerta(self.alerta)
        payload["channels"].append("PUSH")

        self.assertEqual(self.alerta.canais, ["SCREEN"])


if __name__ == "__main__":
    unittest.main()
