import unittest
from datetime import datetime, timezone

from s3.errors import ALERT_NOT_FOUND, INVALID_TRANSITION, ErroS3
from s3.service import AlertService

from fabricas import FUTURO, evento, rota, roteador


class TestProcessarEvento(unittest.TestCase):

    def setUp(self):
        self.service = AlertService(roteador=roteador())

    def test_alerta_do_evento(self):
        """A rota define severidade, destinatários, canais e textos."""

        alerta = self.service.processar_evento_roteado(evento())

        self.assertEqual(alerta.evento_id, "evt-001")
        self.assertEqual(alerta.severidade, "HIGH")
        self.assertEqual(alerta.destinatarios, ["role:supervisor"])
        self.assertEqual(alerta.canais, ["SCREEN", "PUSH"])
        self.assertEqual(alerta.titulo, "EPI ausente: luva")
        self.assertEqual(
            alerta.mensagem, "Pessoa sem luva em galpao-solda há 8 s"
        )
        self.assertEqual(alerta.estado, "CREATED")

    def test_contexto_do_envelope(self):
        """O alerta guarda o contexto usado no envelope de saída."""

        alerta = self.service.processar_evento_roteado(evento())

        self.assertEqual(alerta.origem, "cam0")
        self.assertEqual(alerta.session_id, "sessao-1")
        self.assertEqual(alerta.correlacao_id, "evt-001")
        self.assertEqual(alerta.versao_roteamento, "routing-a5-1")
        self.assertEqual(
            alerta.capturado_em,
            datetime(2026, 9, 23, 14, 29, 59, 870000, tzinfo=timezone.utc),
        )

    def test_evento_sem_rota(self):
        self.assertIsNone(
            self.service.processar_evento_roteado(evento(tipo="ZONE_ENTER"))
        )

    def test_servico_sem_roteador(self):
        with self.assertRaises(ValueError):
            AlertService().processar_evento_roteado(evento())

    def test_evento_invalido(self):
        with self.assertRaises(ValueError):
            self.service.processar_evento_roteado(evento(confianca=1.5))

        self.assertIsNone(self.service.repository.buscar_por_evento("evt-001"))

    def test_mesmo_evento_outras_fases(self):
        """UPDATED e ENDED do mesmo event_id não criam outro alerta."""

        primeiro = self.service.processar_evento_roteado(evento())

        for fase in ("UPDATED", "ENDED"):
            alerta = self.service.processar_evento_roteado(
                evento(fase=fase, duracao_ms=20000)
            )
            self.assertEqual(alerta.alerta_id, primeiro.alerta_id)

        historico = self.service.repository.buscar_historico(primeiro.alerta_id)
        self.assertEqual(len(historico), 1)

    def test_updated_sem_alerta_cria(self):
        """UPDATED sem alerta: o STARTED se perdeu e a violação continua."""

        alerta = self.service.processar_evento_roteado(evento(fase="UPDATED"))

        self.assertEqual(alerta.estado, "CREATED")

    def test_ended_sem_alerta_nao_cria(self):
        """ENDED sem alerta: a violação já terminou, nenhum alerta novo."""

        with self.assertLogs("s3.service", level="WARNING"):
            alerta = self.service.processar_evento_roteado(evento(fase="ENDED"))

        self.assertIsNone(alerta)
        self.assertIsNone(self.service.repository.buscar_por_evento("evt-001"))

    def test_ended_nao_encerra_alerta(self):
        """Fim da violação não é encerramento do atendimento."""

        primeiro = self.service.processar_evento_roteado(evento())

        alerta = self.service.processar_evento_roteado(evento(fase="ENDED"))

        self.assertEqual(alerta.alerta_id, primeiro.alerta_id)
        self.assertEqual(alerta.estado, "CREATED")

    def test_ids_diferentes(self):
        primeiro = self.service.processar_evento(evento(), rota())
        segundo = self.service.processar_evento(evento(evento_id="evt-002"), rota())

        self.assertNotEqual(primeiro.alerta_id, segundo.alerta_id)


class TestCriarAlertaPorComando(unittest.TestCase):

    def setUp(self):
        self.service = AlertService()

    def criar(self, **alteracoes):
        dados = dict(
            titulo="Acesso negado",
            mensagem="Crachá recusado",
            severidade="MEDIUM",
            destinatarios=["group:portaria"],
            canais=["SCREEN"],
        )
        dados.update(alteracoes)
        return self.service.criar_alerta(**dados)

    def test_criar_sem_evento(self):
        alerta = self.criar(correlacao_id="m-1")

        self.assertIsNone(alerta.evento_id)
        self.assertEqual(alerta.estado, "CREATED")
        self.assertEqual(alerta.correlacao_id, "m-1")

    def test_criar_citando_evento_ja_alertado(self):
        """Alerta de negócio pode citar um evento que já tem alerta."""

        service = AlertService(roteador=roteador())
        service.processar_evento_roteado(evento())
        self.service = service

        alerta = self.criar(evento_id="evt-001")

        self.assertEqual(alerta.evento_id, "evt-001")

    def test_destinatario_invalido(self):
        with self.assertRaises(ErroS3):
            self.criar(destinatarios=["portaria"])


class TestCicloDeVida(unittest.TestCase):
    """Transições de estado e comandos repetidos."""

    def setUp(self):
        self.service = AlertService(roteador=roteador())
        self.alerta_id = self.service.processar_evento_roteado(evento()).alerta_id

    def acoes(self):
        return [
            registro.acao
            for registro in self.service.repository.buscar_historico(
                self.alerta_id
            )
        ]

    def estado(self):
        return self.service.repository.buscar_por_id(self.alerta_id).estado

    def test_reconhecer(self):
        alerta = self.service.reconhecer_alerta(
            self.alerta_id, "user:maria", "verificado"
        )

        self.assertEqual(alerta.estado, "ACKNOWLEDGED")
        self.assertEqual(alerta.reconhecido_por, "user:maria")
        self.assertIsNotNone(alerta.reconhecido_em)

        ultimo = self.service.repository.buscar_historico(self.alerta_id)[-1]
        self.assertEqual(ultimo.motivo, "verificado")

    def test_reconhecer_duas_vezes(self):
        """ACK repetido é rejeitado e não duplica o histórico."""

        self.service.reconhecer_alerta(self.alerta_id, "user:maria")

        with self.assertRaises(ErroS3) as contexto:
            self.service.reconhecer_alerta(self.alerta_id, "user:maria")

        self.assertEqual(contexto.exception.codigo, INVALID_TRANSITION)
        self.assertEqual(self.acoes(), ["CREATED", "ACKNOWLEDGED"])

    def test_silenciar_com_prazo(self):
        alerta = self.service.silenciar_alerta(
            self.alerta_id, "user:maria", FUTURO
        )

        self.assertEqual(alerta.estado, "MUTED")
        self.assertEqual(alerta.silenciado_ate, FUTURO)

    def test_silenciar_sem_prazo(self):
        with self.assertRaises(ValueError):
            self.service.silenciar_alerta(self.alerta_id, "user:maria", None)

        self.assertEqual(self.estado(), "CREATED")

    def test_silenciado_nao_pode_ser_reconhecido(self):
        self.service.silenciar_alerta(self.alerta_id, "user:maria", FUTURO)

        with self.assertRaises(ErroS3):
            self.service.reconhecer_alerta(self.alerta_id, "user:maria")

    def test_ciclo_completo(self):
        """CREATED → ACKNOWLEDGED → MUTED → CLOSED."""

        self.service.reconhecer_alerta(self.alerta_id, "user:maria")
        self.service.silenciar_alerta(self.alerta_id, "user:maria", FUTURO)
        alerta = self.service.encerrar_alerta(self.alerta_id, "user:joao")

        self.assertEqual(alerta.estado, "CLOSED")
        self.assertEqual(alerta.encerrado_por, "user:joao")
        self.assertEqual(alerta.reconhecido_por, "user:maria")
        self.assertEqual(
            self.acoes(), ["CREATED", "ACKNOWLEDGED", "MUTED", "CLOSED"]
        )

    def test_encerrado_e_estado_final(self):
        self.service.encerrar_alerta(self.alerta_id, "user:maria")

        for comando in (
            lambda: self.service.reconhecer_alerta(self.alerta_id, "user:x"),
            lambda: self.service.silenciar_alerta(self.alerta_id, "user:x", FUTURO),
            lambda: self.service.encerrar_alerta(self.alerta_id, "user:x"),
        ):
            with self.assertRaises(ErroS3):
                comando()

        self.assertEqual(self.acoes(), ["CREATED", "CLOSED"])

    def test_alerta_inexistente(self):
        with self.assertRaises(ErroS3) as contexto:
            self.service.encerrar_alerta("alerta-x", "user:maria")

        self.assertEqual(contexto.exception.codigo, ALERT_NOT_FOUND)

    def test_comando_sem_autor_nao_muda_estado(self):
        for autor in ("", "   "):
            with self.assertRaises(ValueError):
                self.service.encerrar_alerta(self.alerta_id, autor)

        self.assertEqual(self.estado(), "CREATED")
        self.assertEqual(self.acoes(), ["CREATED"])

    def test_evento_repetido_apos_mudanca_de_estado(self):
        """Reenvio do evento não recria nem reseta o alerta."""

        self.service.reconhecer_alerta(self.alerta_id, "user:maria")

        alerta = self.service.processar_evento_roteado(evento())

        self.assertEqual(alerta.alerta_id, self.alerta_id)
        self.assertEqual(alerta.estado, "ACKNOWLEDGED")


class TestConsultarAlertas(unittest.TestCase):

    def test_filtrar_por_estado(self):
        service = AlertService(roteador=roteador())

        primeiro = service.processar_evento_roteado(evento())
        service.processar_evento_roteado(evento(evento_id="evt-002"))
        service.encerrar_alerta(primeiro.alerta_id, "user:maria")

        encerrados, proximo = service.consultar_alertas(estado="CLOSED")

        self.assertEqual([a.alerta_id for a in encerrados], [primeiro.alerta_id])
        self.assertIsNone(proximo)


if __name__ == "__main__":
    unittest.main()
