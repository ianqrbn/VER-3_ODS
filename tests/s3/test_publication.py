
import json
import unittest

from s3.ingestion import IngestorEventos
from s3.service import AlertService

from fabricas import FUTURO, PublicadorFalso, evento, mensagem_evento, roteador


class PublicadorComFalha:
    """Simula o barramento indisponível."""

    def publicar(self, mensagem):
        raise ConnectionError("barramento indisponível")


class TestPublicacaoAlertas(unittest.TestCase):

    def setUp(self):
        self.publicador = PublicadorFalso()

        self.service = AlertService(
            roteador=roteador(),
            publicador=self.publicador,
        )

    def estados(self):
        return [
            mensagem["payload"]["state"]
            for mensagem in self.publicador.mensagens
        ]

    def test_publica_ao_criar(self):
        """Um alerta novo gera uma mensagem ods.s3.alert."""

        alerta = self.service.processar_evento_roteado(evento())

        self.assertEqual(len(self.publicador.mensagens), 1)

        mensagem = self.publicador.mensagens[0]

        self.assertEqual(mensagem["schema"], "ods.s3.alert")
        self.assertEqual(mensagem["payload"]["alert_id"], alerta.alerta_id)
        self.assertEqual(mensagem["payload"]["state"], "CREATED")
        self.assertEqual(mensagem["correlation_id"], "evt-001")

    def test_evento_repetido_nao_publica_de_novo(self):
        self.service.processar_evento_roteado(evento())
        self.service.processar_evento_roteado(evento(fase="UPDATED"))

        self.assertEqual(len(self.publicador.mensagens), 1)

    def test_publica_cada_mudanca_de_estado(self):
        alerta = self.service.processar_evento_roteado(evento())

        self.service.reconhecer_alerta(alerta.alerta_id, "user:maria")
        self.service.silenciar_alerta(alerta.alerta_id, "user:maria", FUTURO)
        self.service.encerrar_alerta(alerta.alerta_id, "user:maria")

        self.assertEqual(
            self.estados(),
            ["CREATED", "ACKNOWLEDGED", "MUTED", "CLOSED"],
        )

        ultimo = self.publicador.mensagens[-1]["payload"]
        self.assertEqual(ultimo["acknowledged_by"], "user:maria")
        self.assertEqual(ultimo["closed_by"], "user:maria")

    def test_sequence_crescente_por_sessao(self):
        alerta = self.service.processar_evento_roteado(evento())
        self.service.reconhecer_alerta(alerta.alerta_id, "user:maria")

        self.assertEqual(
            [m["sequence"] for m in self.publicador.mensagens], [0, 1]
        )

    def test_comando_rejeitado_nao_publica(self):
        alerta = self.service.processar_evento_roteado(evento())
        self.service.reconhecer_alerta(alerta.alerta_id, "user:maria")

        with self.assertRaises(ValueError):
            self.service.reconhecer_alerta(alerta.alerta_id, "user:maria")

        self.assertEqual(self.estados(), ["CREATED", "ACKNOWLEDGED"])

    def test_evento_invalido_nao_publica(self):
        with self.assertRaises(ValueError):
            self.service.processar_evento_roteado(evento(confianca=1.5))

        self.assertEqual(self.publicador.mensagens, [])

    def test_alerta_por_comando_publica(self):
        self.service.criar_alerta(
            "Acesso negado", "Crachá recusado", "MEDIUM",
            ["group:portaria"], ["SCREEN"], correlacao_id="m-1",
        )

        mensagem = self.publicador.mensagens[0]

        self.assertEqual(mensagem["correlation_id"], "m-1")
        self.assertNotIn("event_id", mensagem["payload"])

    def test_sem_publicador(self):
        alerta = AlertService(roteador=roteador()).processar_evento_roteado(
            evento()
        )

        self.assertEqual(alerta.estado, "CREATED")

    def test_falha_na_publicacao(self):
        """
        Falha do barramento é repassada a quem chamou,
        mas o alerta já fica salvo (limitação conhecida).
        """

        service = AlertService(
            roteador=roteador(), publicador=PublicadorComFalha()
        )

        with self.assertRaises(ConnectionError):
            service.processar_evento_roteado(evento())

        self.assertIsNotNone(service.repository.buscar_por_evento("evt-001"))

    def test_fluxo_entrada_ate_saida(self):
        """ods.s2.event entra pelo ingestor e sai como ods.s3.alert."""

        IngestorEventos(self.service).receber(json.dumps(mensagem_evento()))

        saida = self.publicador.mensagens[0]

        self.assertEqual(saida["session_id"], "9c2a1f3e-4d5b-4c6a-9e8f-0a1b2c3d4e5f")
        self.assertEqual(saida["captured_at"], "2026-09-23T14:29:59.870Z")
        self.assertEqual(saida["payload"]["severity"], "HIGH")
        self.assertEqual(saida["payload"]["channels"], ["SCREEN", "PUSH"])


if __name__ == "__main__":
    unittest.main()
