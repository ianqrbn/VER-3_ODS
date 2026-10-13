
import unittest

from s3.ingestion import IngestorEventos
from s3.repository import AlertRepository
from s3.routing import ConfiguracaoRoteamento, RoteadorAlertas
from s3.service import AlertService
from s3.subscription import ConectorEventos


class AssinanteFalso:
    """
    Simula um assinante de barramento para testes, sem broker real.

    Guarda o callback registrado e permite "publicar" mensagens
    manualmente, como se o B2 estivesse entregando eventos.
    """

    def __init__(self):
        self.callback = None

    def assinar(self, callback):
        self.callback = callback

    def publicar(self, mensagem):
        if self.callback is None:
            raise RuntimeError("Nenhum callback registrado.")

        return self.callback(mensagem)


class TestConectorEventos(unittest.TestCase):

    def setUp(self):
        """Prepara um S3 completo e um assinante falso no lugar do B2."""

        self.repository = AlertRepository()

        self.regra = ConfiguracaoRoteamento(
            severidade="ALTA",
            destinatarios=("supervisor-01",),
            canais=("SOM", "TELA"),
        )

        self.roteador = RoteadorAlertas(
            {"VIOLACAO_EPI": self.regra}
        )

        self.service = AlertService(
            repository=self.repository,
            roteador=self.roteador,
        )

        self.ingestor = IngestorEventos(self.service)

        self.assinante = AssinanteFalso()

        self.conector = ConectorEventos(
            assinante=self.assinante,
            ingestor=self.ingestor,
        )

        self.mensagem = (
            '{"evento_id": "evt-100", "tipo": "VIOLACAO_EPI", '
            '"origem": "S2", "timestamp": "2026-10-07T10:00:00Z", '
            '"confianca": 0.9}'
        )

    def test_conectar_registra_callback(self):
        """conectar() deve registrar o ingestor como callback do assinante."""

        self.conector.conectar()

        self.assertIsNotNone(self.assinante.callback)
        self.assertEqual(self.assinante.callback, self.ingestor.receber)

    def test_mensagem_publicada_gera_alerta(self):
        """Uma mensagem publicada pelo assinante deve virar um alerta roteado."""

        self.conector.conectar()

        alerta = self.assinante.publicar(self.mensagem)

        self.assertEqual(alerta.evento_id, "evt-100")
        self.assertEqual(alerta.severidade, "ALTA")
        self.assertEqual(alerta.destinatarios, ["supervisor-01"])
        self.assertEqual(alerta.canais, ["SOM", "TELA"])

        alerta_salvo = self.repository.buscar_por_evento("evt-100")

        self.assertIsNotNone(alerta_salvo)
        self.assertEqual(alerta_salvo.alerta_id, alerta.alerta_id)

    def test_publicar_sem_conectar_falha(self):
        """Sem conectar(), o assinante não tem callback para entregar."""

        with self.assertRaises(RuntimeError):
            self.assinante.publicar(self.mensagem)


if __name__ == "__main__":
    unittest.main()
