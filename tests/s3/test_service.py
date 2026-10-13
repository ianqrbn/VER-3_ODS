
import unittest

from s3.contracts import EventoQualificado
from s3.service import AlertService


class TestAlertService(unittest.TestCase):

    def setUp(self):
        """Prepara os dados utilizados em cada teste."""

        self.service = AlertService()

        self.evento = EventoQualificado(
            evento_id="evt-001",
            tipo="VIOLACAO_EPI",
            origem="S2",
            timestamp="2026-09-18T10:00:00Z",
            confianca=0.96,
            pessoa_id="pessoa-37",
            zona_id="producao",
            evidencia_ref="evidencia-001"
        )

    def test_criar_alerta_valido(self):
        """Deve criar um alerta a partir de um evento válido."""

        alerta = self.service.criar_alerta(
            evento=self.evento,
            severidade="ALTA",
            destinatarios=["supervisor-01"],
            canais=["SOM", "TELA"]
        )

        self.assertTrue(alerta.alerta_id)

        self.assertEqual(
            alerta.evento_id,
            self.evento.evento_id
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

        self.assertEqual(alerta.estado, "CRIADO")

    def test_rejeitar_evento_invalido(self):
        """Não deve criar alerta com evento inválido."""

        self.evento.confianca = 1.5

        with self.assertRaises(ValueError):
            self.service.criar_alerta(
                evento=self.evento,
                severidade="ALTA",
                destinatarios=["supervisor-01"],
                canais=["SOM"]
            )

    def test_rejeitar_alerta_sem_destinatarios(self):
        """Não deve aceitar configuração sem destinatários."""

        with self.assertRaises(ValueError):
            self.service.criar_alerta(
                evento=self.evento,
                severidade="ALTA",
                destinatarios=[],
                canais=["SOM"]
            )

    def test_gerar_identificadores_diferentes(self):
        """Deve gerar IDs distintos para duas criações."""

        alerta1 = self.service.criar_alerta(
            evento=self.evento,
            severidade="ALTA",
            destinatarios=["supervisor-01"],
            canais=["SOM"]
        )

        alerta2 = self.service.criar_alerta(
            evento=self.evento,
            severidade="ALTA",
            destinatarios=["supervisor-01"],
            canais=["SOM"]
        )

        self.assertNotEqual(
            alerta1.alerta_id,
            alerta2.alerta_id
        )
    
    def test_processar_evento_invalido(self):
            """Evento inválido não deve ser armazenado."""
    
            self.evento.confianca = 1.5
    
            with self.assertRaises(ValueError):
                self.service.processar_evento(
                    evento=self.evento,
                    severidade="ALTA",
                    destinatarios=["supervisor-01"],
                    canais=["SOM"]
                )
    
            alerta_salvo = self.service.repository.buscar_por_evento(
                self.evento.evento_id
            )
    
            self.assertIsNone(alerta_salvo)
    
    def test_reconhecer_alerta(self):
        evento = EventoQualificado(
        evento_id="evt-001",
        tipo="VIOLACAO_EPI",
        origem="CAMERA",
        timestamp="2026-09-11T10:00:00Z",
        confianca=0.95,
    )

        alerta = self.service.processar_evento(
        evento=evento,
        severidade="ALTA",
        destinatarios=["operador-01"],
        canais=["TELA"],
    )

        resultado = self.service.reconhecer_alerta(
        alerta_id=alerta.alerta_id,
        autor_id="operador-01",
    )

        self.assertEqual(resultado.estado, "RECONHECIDO")
        
    def test_reconhecer_alerta_registra_historico(self):
        evento = EventoQualificado(
        evento_id="evt-002",
        tipo="VIOLACAO_EPI",
        origem="CAMERA",
        timestamp="2026-09-11T10:00:00Z",
        confianca=0.95,
    )

        alerta = self.service.processar_evento(
        evento=evento,
        severidade="ALTA",
        destinatarios=["operador-01"],
        canais=["TELA"],
    )

        self.service.reconhecer_alerta(
        alerta_id=alerta.alerta_id,
        autor_id="operador-01",
    )

        historico = self.service.repository.buscar_historico(
        alerta.alerta_id
    )

        self.assertEqual(len(historico), 2)
        self.assertEqual(historico[1].acao, "RECONHECIDO")
        self.assertEqual(historico[1].autor_id, "operador-01")
    
    def test_processar_evento_salva_alerta(self):
            """O processamento deve armazenar o alerta."""
    
            alerta = self.service.processar_evento(
                evento=self.evento,
                severidade="ALTA",
                destinatarios=["supervisor-01"],
                canais=["SOM", "TELA"]
            )
    
            alerta_salvo = self.service.repository.buscar_por_evento(
                self.evento.evento_id
            )
    
            self.assertIsNotNone(alerta_salvo)
    
            self.assertEqual(
                alerta.alerta_id,
                alerta_salvo.alerta_id
            )
    
    def test_processar_evento_duplicado(self):
            """O mesmo evento não deve criar dois alertas."""
    
            alerta1 = self.service.processar_evento(
                evento=self.evento,
                severidade="ALTA",
                destinatarios=["supervisor-01"],
                canais=["SOM"]
            )
    
            alerta2 = self.service.processar_evento(
                evento=self.evento,
                severidade="ALTA",
                destinatarios=["supervisor-01"],
                canais=["SOM"]
            )
    
            self.assertEqual(
                alerta1.alerta_id,
                alerta2.alerta_id
            )
    
            self.assertIs(alerta1, alerta2)

    def test_reconhecer_alerta(self):
        """Deve marcar o alerta como reconhecido e registrar o autor."""

        alerta = self.service.processar_evento(
            evento=self.evento,
            severidade="ALTA",
            destinatarios=["supervisor-01"],
            canais=["SOM"]
        )

        alerta_atualizado = self.service.reconhecer_alerta(
            alerta_id=alerta.alerta_id,
            autor_id="supervisor-01"
        )

        self.assertEqual(alerta_atualizado.estado, "RECONHECIDO")

        historico = self.service.repository.buscar_historico(
            alerta.alerta_id
        )

        self.assertEqual(len(historico), 2)
        self.assertEqual(historico[1].acao, "RECONHECIDO")
        self.assertEqual(historico[1].autor_id, "supervisor-01")

    def test_reconhecer_alerta_inexistente(self):
        """Não deve reconhecer um alerta que não existe."""

        with self.assertRaises(ValueError):
            self.service.reconhecer_alerta(
                alerta_id="alerta-inexistente",
                autor_id="supervisor-01"
            )

    def test_reconhecer_alerta_silenciado(self):
        """Um alerta já silenciado não pode ser reconhecido."""

        alerta = self.service.processar_evento(
            evento=self.evento,
            severidade="ALTA",
            destinatarios=["supervisor-01"],
            canais=["SOM"]
        )

        self.service.silenciar_alerta(
            alerta_id=alerta.alerta_id,
            autor_id="supervisor-01"
        )

        with self.assertRaises(ValueError):
            self.service.reconhecer_alerta(
                alerta_id=alerta.alerta_id,
                autor_id="supervisor-01"
            )

    def test_silenciar_alerta(self):
        """Deve marcar o alerta como silenciado e registrar o autor."""

        alerta = self.service.processar_evento(
            evento=self.evento,
            severidade="ALTA",
            destinatarios=["supervisor-01"],
            canais=["SOM"]
        )

        alerta_atualizado = self.service.silenciar_alerta(
            alerta_id=alerta.alerta_id,
            autor_id="supervisor-02"
        )

        self.assertEqual(alerta_atualizado.estado, "SILENCIADO")

        historico = self.service.repository.buscar_historico(
            alerta.alerta_id
        )

        self.assertEqual(len(historico), 2)
        self.assertEqual(historico[1].acao, "SILENCIADO")
        self.assertEqual(historico[1].autor_id, "supervisor-02")

    def test_silenciar_alerta_duas_vezes(self):
        """Um alerta já silenciado não pode ser silenciado de novo."""

        alerta = self.service.processar_evento(
            evento=self.evento,
            severidade="ALTA",
            destinatarios=["supervisor-01"],
            canais=["SOM"]
        )

        self.service.silenciar_alerta(
            alerta_id=alerta.alerta_id,
            autor_id="supervisor-01"
        )

        with self.assertRaises(ValueError):
            self.service.silenciar_alerta(
                alerta_id=alerta.alerta_id,
                autor_id="supervisor-01"
            )

    def test_silenciar_alerta_sem_reconhecimento_previo(self):
        """Deve ser possível silenciar direto, sem reconhecer antes."""

        alerta = self.service.processar_evento(
            evento=self.evento,
            severidade="ALTA",
            destinatarios=["supervisor-01"],
            canais=["SOM"]
        )

        alerta_atualizado = self.service.silenciar_alerta(
            alerta_id=alerta.alerta_id,
            autor_id="supervisor-01"
        )

        self.assertEqual(alerta_atualizado.estado, "SILENCIADO")


if __name__ == "__main__":
    unittest.main()