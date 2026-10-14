
import json
import unittest

from s3.errors import ErroS3
from s3.ingestion import IngestorEventos
from s3.service import AlertService

from fabricas import mensagem_evento, roteador, texto_json


class TestIngestorEventos(unittest.TestCase):

    def setUp(self):
        """Prepara os componentes para cada teste."""

        self.service = AlertService(roteador=roteador())
        self.repository = self.service.repository
        self.ingestor = IngestorEventos(self.service)

    def receber(self, dados):
        return self.ingestor.receber(json.dumps(dados))

    def test_receber_arquivo_entrada_json(self):
        """O exemplo jsons/entrada.json deve virar alerta."""

        alerta = self.ingestor.receber(texto_json("entrada.json"))

        self.assertEqual(alerta.evento_id, "6d9f2b1c-3e4a-4b5c-8d6e-7f8a9b0c1d2e")
        self.assertEqual(alerta.severidade, "HIGH")
        self.assertEqual(alerta.titulo, "EPI ausente: luva")

    def test_receber_bytes(self):
        """O Kafka entrega bytes."""

        alerta = self.ingestor.receber(
            json.dumps(mensagem_evento()).encode("utf-8")
        )

        self.assertIsNotNone(alerta)

    def test_json_malformado(self):
        with self.assertRaises(ValueError):
            self.ingestor.receber('{"event_id":')

    def test_envelope_invalido(self):
        """Envelope fora do contrato é rejeitado."""

        for alteracao in (
            {"schema": "ods.s3.alert"},
            {"message_type": "command"},
            {"schema_version": "2.0"},
            {"session_id": None},
        ):
            with self.subTest(alteracao=alteracao):
                with self.assertRaises(ErroS3):
                    self.receber(mensagem_evento(**alteracao))

    def test_formato_antigo_rejeitado(self):
        """O formato provisório, sem envelope, não é mais aceito."""

        antigo = {
            "evento_id": "evt-001",
            "tipo": "VIOLACAO_EPI",
            "origem": "S2",
            "timestamp": "2026-09-18T10:00:00Z",
            "confianca": 0.96,
        }

        with self.assertRaises(ErroS3):
            self.receber(antigo)

    def test_payload_incompleto(self):
        dados = mensagem_evento()
        del dados["payload"]["rule_id"]

        with self.assertRaises(ErroS3):
            self.receber(dados)

        self.assertIsNone(
            self.repository.buscar_por_evento(dados["payload"]["event_id"])
        )

    def test_evento_sem_rota(self):
        """Tipo sem rota: nenhum alerta, sem erro."""

        self.assertIsNone(
            self.receber(mensagem_evento({"event_type": "ZONE_ENTER"}))
        )

    def test_mesma_mensagem_duas_vezes(self):
        """O message_id repetido é descartado."""

        dados = mensagem_evento()

        self.assertIsNotNone(self.receber(dados))
        self.assertIsNone(self.receber(dados))

    def test_mesmo_evento_outra_mensagem(self):
        """Outra mensagem (fase UPDATED) do mesmo evento devolve o mesmo alerta."""

        primeiro = self.receber(mensagem_evento())
        segundo = self.receber(
            mensagem_evento({"phase": "UPDATED", "duration_ms": 15000})
        )

        self.assertEqual(primeiro.alerta_id, segundo.alerta_id)
        self.assertEqual(
            len(self.repository.buscar_historico(primeiro.alerta_id)), 1
        )

    def test_ended_sem_alerta_marca_processada(self):
        """ENDED sem alerta não gera alerta nem fica para reprocessar."""

        dados = mensagem_evento({"phase": "ENDED"})

        with self.assertLogs("s3.service", level="WARNING"):
            self.assertIsNone(self.receber(dados))

        self.assertTrue(
            self.repository.mensagem_processada(dados["message_id"])
        )

    def test_falha_permite_reentrega(self):
        """Mensagem que falhou não é marcada como processada."""

        dados = mensagem_evento({"confidence": 1.5})

        with self.assertRaises(ErroS3):
            self.receber(dados)

        self.assertFalse(
            self.repository.mensagem_processada(dados["message_id"])
        )


if __name__ == "__main__":
    unittest.main()
