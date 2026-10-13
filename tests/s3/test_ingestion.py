
import json
import unittest

from s3.ingestion import IngestorEventos
from s3.repository import AlertRepository
from s3.routing import (
    ConfiguracaoRoteamento,
    RoteadorAlertas,
)
from s3.service import AlertService


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


if __name__ == "__main__":
    unittest.main()