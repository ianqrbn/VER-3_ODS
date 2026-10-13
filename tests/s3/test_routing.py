
import unittest

from s3.contracts import EventoQualificado
from s3.routing import (
    ConfiguracaoRoteamento,
    RoteadorAlertas,
)


class TestRoteadorAlertas(unittest.TestCase):

    def setUp(self):
        """Prepara um evento e uma configuração válida."""

        self.evento = EventoQualificado(
            evento_id="evt-001",
            tipo="VIOLACAO_EPI",
            origem="S2",
            timestamp="2026-09-18T10:00:00Z",
            confianca=0.96,
        )

        self.configuracao = ConfiguracaoRoteamento(
            severidade="ALTA",
            destinatarios=("supervisor-01",),
            canais=("SOM", "TELA"),
        )

    def test_resolver_roteamento(self):
        """Deve encontrar a configuração do evento."""

        roteador = RoteadorAlertas(
            regras={
                "VIOLACAO_EPI": self.configuracao
            }
        )

        resultado = roteador.resolver(self.evento)

        self.assertEqual(resultado.severidade, "ALTA")

        self.assertEqual(
            resultado.destinatarios,
            ("supervisor-01",)
        )

        self.assertEqual(
            resultado.canais,
            ("SOM", "TELA")
        )

    def test_evento_sem_roteamento(self):
        """Deve rejeitar um tipo sem configuração."""

        roteador = RoteadorAlertas(
            regras={
                "OUTRO_EVENTO": self.configuracao
            }
        )

        with self.assertRaises(ValueError):
            roteador.resolver(self.evento)

    def test_canal_invalido(self):
        """Deve rejeitar canais desconhecidos."""

        with self.assertRaises(ValueError):
            ConfiguracaoRoteamento(
                severidade="ALTA",
                destinatarios=("supervisor-01",),
                canais=("EMAIL",),
            )

    def test_destinatario_vazio(self):
        """Deve rejeitar destinatários vazios."""

        with self.assertRaises(ValueError):
            ConfiguracaoRoteamento(
                severidade="ALTA",
                destinatarios=("",),
                canais=("SOM",),
            )

    def test_severidade_vazia(self):
        """Deve exigir severidade."""

        with self.assertRaises(ValueError):
            ConfiguracaoRoteamento(
                severidade="",
                destinatarios=("supervisor-01",),
                canais=("SOM",),
            )

    def test_roteador_sem_regras(self):
        """Deve exigir pelo menos uma configuração."""

        with self.assertRaises(ValueError):
            RoteadorAlertas(regras={})

    def test_evento_invalido(self):
        """Não deve rotear eventos inválidos."""

        roteador = RoteadorAlertas(
            regras={
                "VIOLACAO_EPI": self.configuracao
            }
        )

        self.evento.confianca = 1.5

        with self.assertRaises(ValueError):
            roteador.resolver(self.evento)


if __name__ == "__main__":
    unittest.main()