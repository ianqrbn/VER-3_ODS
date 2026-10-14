
import json
import unittest

from s3.commands import ProcessadorComandos
from s3.ingestion import IngestorEventos
from s3.service import AlertService
from s3.subscription import ConectorComandos, ConectorEventos, DespachanteS3

from fabricas import (
    AssinanteFalso,
    PublicadorFalso,
    comando,
    mensagem_evento,
    roteador,
)


class TestConectorEventos(unittest.TestCase):

    def setUp(self):
        """Prepara um S3 completo e um assinante falso no lugar do Kafka."""

        self.service = AlertService(roteador=roteador())
        self.assinante = AssinanteFalso()
        self.conector = ConectorEventos(
            self.assinante, IngestorEventos(self.service)
        )

    def test_conectar_registra_callback(self):
        self.conector.conectar()

        self.assertEqual(self.assinante.callback, self.conector.entregar)

    def test_mensagem_publicada_gera_alerta(self):
        self.conector.conectar()

        alerta = self.assinante.publicar(json.dumps(mensagem_evento()))

        self.assertEqual(alerta.severidade, "HIGH")

    def test_mensagem_invalida_descartada_com_log(self):
        """Mensagem inválida não interrompe o consumo: é descartada e logada."""

        self.conector.conectar()

        with self.assertLogs("s3.subscription", level="WARNING") as logs:
            resultado = self.assinante.publicar('{"quebrado":')

        self.assertIsNone(resultado)
        self.assertIn("descartada", logs.output[0])

    def test_publicar_sem_conectar_falha(self):
        with self.assertRaises(RuntimeError):
            self.assinante.publicar(json.dumps(mensagem_evento()))


class TestDespachante(unittest.TestCase):

    def setUp(self):
        service = AlertService(roteador=roteador())
        self.respostas = PublicadorFalso()
        self.assinante = AssinanteFalso()

        DespachanteS3(
            ConectorEventos(self.assinante, IngestorEventos(service)),
            ConectorComandos(
                self.assinante, ProcessadorComandos(service), self.respostas
            ),
        ).conectar(self.assinante)

    def test_evento_e_comando_no_mesmo_assinante(self):
        """ods.s2.event vai ao ingestor; comandos geram reply publicada."""

        alerta = self.assinante.publicar(json.dumps(mensagem_evento()))

        self.assinante.publicar(json.dumps(comando(
            "ods.s3.alert_action.command",
            {"alert_id": alerta.alerta_id, "action": "ACKNOWLEDGE", "actor": "user:maria"},
        )))

        self.assertEqual(len(self.respostas.mensagens), 1)
        self.assertEqual(
            self.respostas.mensagens[0]["payload"]["state"], "ACKNOWLEDGED"
        )

    def test_comando_invalido_sem_reply(self):
        with self.assertLogs("s3.subscription", level="WARNING"):
            self.assinante.publicar(json.dumps(comando(
                "ods.s3.alert_action.command", {}, target="S4"
            )))

        self.assertEqual(self.respostas.mensagens, [])

    def test_json_invalido(self):
        with self.assertLogs("s3.subscription", level="WARNING"):
            self.assertIsNone(self.assinante.publicar(b"\xff"))


if __name__ == "__main__":
    unittest.main()
