
import json
import unittest
from pathlib import Path

from s3.ingestion import IngestorEventos
from s3.repository import AlertRepository
from s3.routing import (
    ConfiguracaoRoteamento,
    RoteadorAlertas,
)
from s3.service import AlertService

ARQUIVO_ENTRADA = (
    Path(__file__).resolve().parents[2] / "jsons" / "entrada.json"
)


class TestIngestorEventos(unittest.TestCase):

    def setUp(self):
        """Prepara os componentes para cada teste."""

        self.repository = AlertRepository()

        configuracao = ConfiguracaoRoteamento(
            severidade="ALTA",
            destinatarios=("supervisor-01",),
            canais=("SOM", "TELA"),
        )

        roteador = RoteadorAlertas(
            regras={
                "VIOLACAO_EPI": configuracao
            }
        )

        service = AlertService(
            repository=self.repository,
            roteador=roteador,
        )

        self.ingestor = IngestorEventos(service)

        self.dados = {
            "evento_id": "evt-001",
            "tipo": "VIOLACAO_EPI",
            "origem": "S2",
            "timestamp": "2026-09-18T10:00:00Z",
            "confianca": 0.96,
            "pessoa_id": "pessoa-37",
            "zona_id": "producao",
            "evidencia_ref": "evidencia-001",
        }

    def test_receber_evento_valido(self):
        """Deve transformar JSON em alerta."""

        mensagem = json.dumps(self.dados)

        alerta = self.ingestor.receber(mensagem)

        self.assertEqual(
            alerta.evento_id,
            "evt-001"
        )

        self.assertEqual(
            alerta.severidade,
            "ALTA"
        )

        self.assertEqual(
            alerta.destinatarios,
            ["supervisor-01"]
        )

        self.assertEqual(
            alerta.canais,
            ["SOM", "TELA"]
        )

        alerta_salvo = self.repository.buscar_por_evento(
            "evt-001"
        )

        self.assertIs(alerta, alerta_salvo)

    def test_json_malformado(self):
        """Deve rejeitar uma mensagem JSON inválida."""

        mensagem = '{"evento_id":'

        with self.assertRaises(ValueError):
            self.ingestor.receber(mensagem)

    def test_json_nao_objeto(self):
        """A mensagem precisa conter um objeto JSON."""

        mensagem = json.dumps(
            ["evento", "invalido"]
        )

        with self.assertRaises(ValueError):
            self.ingestor.receber(mensagem)

    def test_evento_sem_campo_obrigatorio(self):
        """Deve rejeitar campos obrigatórios ausentes."""

        del self.dados["evento_id"]

        mensagem = json.dumps(self.dados)

        with self.assertRaises(ValueError):
            self.ingestor.receber(mensagem)

    def test_evento_sem_roteamento(self):
        """Não deve criar alerta sem regra configurada."""

        self.dados["tipo"] = "EVENTO_DESCONHECIDO"

        mensagem = json.dumps(self.dados)

        with self.assertRaises(ValueError):
            self.ingestor.receber(mensagem)

        self.assertIsNone(
            self.repository.buscar_por_evento("evt-001")
        )

    def test_evento_repetido(self):
        """Não deve criar outro alerta para o mesmo evento."""

        mensagem = json.dumps(self.dados)

        alerta1 = self.ingestor.receber(mensagem)
        alerta2 = self.ingestor.receber(mensagem)

        self.assertEqual(
            alerta1.alerta_id,
            alerta2.alerta_id
        )

        historico = self.repository.buscar_historico(
            alerta1.alerta_id
        )

        self.assertEqual(len(historico), 1)
        self.assertEqual(historico[0].acao, "CRIADO")

    def _envelope(self):
        return {
            "message_type": "event",
            "schema": "ods.eventos.qualificados",
            "schema_version": "1.0",
            "producer": "S2",
            "published_at": "2026-09-18T10:00:01Z",
            "payload": self.dados,
        }

    def test_receber_envelope_documentado(self):
        """Deve aceitar o evento dentro do envelope."""

        alerta = self.ingestor.receber(
            json.dumps(self._envelope())
        )

        self.assertEqual(alerta.evento_id, "evt-001")
        self.assertEqual(alerta.evidencia_ref, "evidencia-001")

    def test_receber_arquivo_entrada_json(self):
        """O exemplo jsons/entrada.json deve ser aceito."""

        with open(ARQUIVO_ENTRADA, encoding="utf-8") as arquivo:
            mensagem = arquivo.read()

        alerta = self.ingestor.receber(mensagem)

        self.assertEqual(alerta.evento_id, "evt-001")
        self.assertEqual(alerta.severidade, "ALTA")

    def test_envelope_com_payload_nao_objeto(self):
        """O payload precisa ser um objeto JSON."""

        envelope = self._envelope()
        envelope["payload"] = ["evento"]

        with self.assertRaises(ValueError):
            self.ingestor.receber(json.dumps(envelope))

    def test_envelope_com_tipo_invalido(self):
        """Deve rejeitar message_type diferente de event."""

        envelope = self._envelope()
        envelope["message_type"] = "command"

        with self.assertRaises(ValueError):
            self.ingestor.receber(json.dumps(envelope))

    def test_envelope_com_schema_invalido(self):
        """Deve rejeitar schema diferente do esperado."""

        envelope = self._envelope()
        envelope["schema"] = "ods.alertas.alerta"

        with self.assertRaises(ValueError):
            self.ingestor.receber(json.dumps(envelope))

    def test_envelope_sem_producer(self):
        """O envelope precisa identificar o produtor."""

        envelope = self._envelope()
        del envelope["producer"]

        with self.assertRaises(ValueError):
            self.ingestor.receber(json.dumps(envelope))

    def test_envelope_com_payload_incompleto(self):
        """Campos obrigatórios do payload continuam exigidos."""

        envelope = self._envelope()
        del envelope["payload"]["tipo"]

        with self.assertRaises(ValueError):
            self.ingestor.receber(json.dumps(envelope))

    def test_confianca_nao_numerica(self):
        """Confiança em texto deve gerar ValueError."""

        self.dados["confianca"] = "0.9"

        with self.assertRaises(ValueError):
            self.ingestor.receber(json.dumps(self.dados))


if __name__ == "__main__":
    unittest.main()