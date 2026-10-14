
import json
import unittest

from s3.contracts import EventoQualificado
from s3.ingestion import IngestorEventos
from s3.routing import ConfiguracaoRoteamento, RoteadorAlertas
from s3.service import AlertService


class PublicadorFalso:
    """Substituto do adaptador real do B2: só guarda as mensagens."""

    def __init__(self):
        self.mensagens = []

    def publicar(self, mensagem):
        self.mensagens.append(json.loads(mensagem))


class PublicadorComFalha:
    """Simula o barramento indisponível."""

    def publicar(self, mensagem):
        raise ConnectionError("barramento indisponível")


class TestPublicacaoAlertas(unittest.TestCase):

    def setUp(self):
        self.publicador = PublicadorFalso()

        roteador = RoteadorAlertas({
            "VIOLACAO_EPI": ConfiguracaoRoteamento(
                severidade="ALTA",
                destinatarios=("supervisor-01",),
                canais=("SOM", "TELA"),
            )
        })

        self.service = AlertService(
            roteador=roteador,
            publicador=self.publicador,
        )

        self.evento = EventoQualificado(
            evento_id="evt-pub",
            tipo="VIOLACAO_EPI",
            origem="S2",
            timestamp="2026-09-18T10:00:00Z",
            confianca=0.96,
        )

    def _estados(self):
        return [
            mensagem["payload"]["estado"]
            for mensagem in self.publicador.mensagens
        ]

    def test_publica_ao_criar(self):
        """Um alerta novo gera uma mensagem de saída."""

        alerta = self.service.processar_evento_roteado(self.evento)

        self.assertEqual(len(self.publicador.mensagens), 1)

        mensagem = self.publicador.mensagens[0]

        self.assertEqual(mensagem["schema"], "ods.alertas.alerta")
        self.assertEqual(mensagem["producer"], "S3")
        self.assertEqual(
            mensagem["payload"]["alerta_id"],
            alerta.alerta_id
        )
        self.assertEqual(mensagem["payload"]["estado"], "CRIADO")

    def test_evento_repetido_nao_publica_de_novo(self):
        """Duplicata de evento não gera nova mensagem."""

        self.service.processar_evento_roteado(self.evento)
        self.service.processar_evento_roteado(self.evento)

        self.assertEqual(len(self.publicador.mensagens), 1)

    def test_publica_cada_mudanca_de_estado(self):
        """Cada transição publica o estado atual do alerta."""

        alerta = self.service.processar_evento_roteado(self.evento)

        self.service.reconhecer_alerta(alerta.alerta_id, "sup-01")
        self.service.silenciar_alerta(alerta.alerta_id, "sup-01")
        self.service.encerrar_alerta(alerta.alerta_id, "sup-01")

        self.assertEqual(
            self._estados(),
            ["CRIADO", "RECONHECIDO", "SILENCIADO", "ENCERRADO"],
        )

    def test_comando_rejeitado_nao_publica(self):
        """Transição inválida não gera mensagem."""

        alerta = self.service.processar_evento_roteado(self.evento)
        self.service.reconhecer_alerta(alerta.alerta_id, "sup-01")

        with self.assertRaises(ValueError):
            self.service.reconhecer_alerta(alerta.alerta_id, "sup-01")

        self.assertEqual(self._estados(), ["CRIADO", "RECONHECIDO"])

    def test_evento_invalido_nao_publica(self):
        """Evento rejeitado não gera mensagem."""

        self.evento.confianca = 1.5

        with self.assertRaises(ValueError):
            self.service.processar_evento_roteado(self.evento)

        self.assertEqual(self.publicador.mensagens, [])

    def test_sem_publicador(self):
        """Sem publicador, o serviço continua funcionando."""

        service = AlertService()

        alerta = service.processar_evento(
            evento=self.evento,
            severidade="ALTA",
            destinatarios=["supervisor-01"],
            canais=["SOM"],
        )

        self.assertEqual(alerta.estado, "CRIADO")

    def test_falha_na_publicacao(self):
        """
        Falha do barramento é repassada a quem chamou,
        mas o alerta já fica salvo (limitação conhecida).
        """

        service = AlertService(publicador=PublicadorComFalha())

        with self.assertRaises(ConnectionError):
            service.processar_evento(
                evento=self.evento,
                severidade="ALTA",
                destinatarios=["supervisor-01"],
                canais=["SOM"],
            )

        self.assertIsNotNone(
            service.repository.buscar_por_evento("evt-pub")
        )

    def test_fluxo_entrada_ate_saida(self):
        """Mensagem do S2 entra pelo ingestor e sai publicada."""

        ingestor = IngestorEventos(self.service)

        entrada = {
            "message_type": "event",
            "schema": "ods.eventos.qualificados",
            "schema_version": "1.0",
            "producer": "S2",
            "published_at": "2026-09-18T10:00:01Z",
            "payload": {
                "evento_id": "evt-fluxo",
                "tipo": "VIOLACAO_EPI",
                "origem": "CAMERA-01",
                "timestamp": "2026-09-18T10:00:00Z",
                "confianca": 0.9,
                "evidencia_ref": "evidencia-fluxo",
            },
        }

        ingestor.receber(json.dumps(entrada))

        saida = self.publicador.mensagens[0]["payload"]

        self.assertEqual(saida["evento_id"], "evt-fluxo")
        self.assertEqual(saida["severidade"], "ALTA")
        self.assertEqual(saida["canais"], ["SOM", "TELA"])
        self.assertEqual(saida["evidencia_ref"], "evidencia-fluxo")


if __name__ == "__main__":
    unittest.main()
