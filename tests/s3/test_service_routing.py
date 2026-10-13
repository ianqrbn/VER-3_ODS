
import unittest

from s3.contracts import EventoQualificado
from s3.repository import AlertRepository
from s3.routing import (
    ConfiguracaoRoteamento,
    RoteadorAlertas,
)
from s3.service import AlertService


class TestIntegracaoRoteamento(unittest.TestCase):

    def setUp(self):
        """Prepara o serviço com um roteador configurado."""

        self.evento = EventoQualificado(
            evento_id="evt-001",
            tipo="VIOLACAO_EPI",
            origem="S2",
            timestamp="2026-09-18T10:00:00Z",
            confianca=0.96,
            evidencia_ref="evidencia-001",
        )

        self.configuracao = ConfiguracaoRoteamento(
            severidade="ALTA",
            destinatarios=("supervisor-01",),
            canais=("SOM", "TELA"),
        )

        self.roteador = RoteadorAlertas(
            regras={
                "VIOLACAO_EPI": self.configuracao
            }
        )

        self.repository = AlertRepository()

        self.service = AlertService(
            repository=self.repository,
            roteador=self.roteador,
        )

    def test_processamento_roteado(self):
        """Deve aplicar automaticamente a configuração."""

        alerta = self.service.processar_evento_roteado(
            self.evento
        )

        self.assertEqual(alerta.severidade, "ALTA")

        self.assertEqual(
            alerta.destinatarios,
            ["supervisor-01"]
        )

        self.assertEqual(
            alerta.canais,
            ["SOM", "TELA"]
        )

        self.assertEqual(
            alerta.evidencia_ref,
            "evidencia-001"
        )

        alerta_salvo = self.repository.buscar_por_evento(
            "evt-001"
        )

        self.assertIs(alerta, alerta_salvo)

    def test_servico_sem_roteador(self):
        """Deve rejeitar processamento sem roteador."""

        service = AlertService(
            repository=self.repository
        )

        with self.assertRaises(ValueError):
            service.processar_evento_roteado(
                self.evento
            )

    def test_evento_sem_regra(self):
        """Deve rejeitar evento não configurado."""

        self.evento.tipo = "EVENTO_DESCONHECIDO"

        with self.assertRaises(ValueError):
            self.service.processar_evento_roteado(
                self.evento
            )

        self.assertIsNone(
            self.repository.buscar_por_evento("evt-001")
        )

    def test_evento_duplicado(self):
        """Não deve criar dois alertas para o mesmo evento."""

        alerta1 = self.service.processar_evento_roteado(
            self.evento
        )

        alerta2 = self.service.processar_evento_roteado(
            self.evento
        )

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