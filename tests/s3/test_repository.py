
import unittest
from datetime import datetime, timezone

from s3.alert import Alerta
from s3.history import RegistroHistorico
from s3.repository import AlertRepository


def novo_alerta(numero=1, **alteracoes):
    dados = dict(
        alerta_id=f"alerta-{numero:03d}",
        evento_id=f"evt-{numero:03d}",
        severidade="HIGH",
        destinatarios=["role:supervisor"],
        canais=["SOUND"],
        titulo="EPI ausente",
        mensagem="Pessoa sem luva",
        criado_em=datetime(2026, 9, 23, 14, numero, tzinfo=timezone.utc),
    )
    dados.update(alteracoes)
    return Alerta(**dados)


class TestAlertRepository(unittest.TestCase):

    def setUp(self):
        """Cria um repositório com um alerta salvo."""

        self.repository = AlertRepository()
        self.alerta = novo_alerta()
        self.repository.salvar(self.alerta)

    def test_salvar_alerta(self):
        """Deve armazenar um alerta válido."""

        salvo = self.repository.buscar_por_id("alerta-001")

        self.assertEqual(salvo.alerta_id, "alerta-001")

    def test_buscar_por_evento(self):
        """Deve localizar o alerta pelo evento de origem."""

        salvo = self.repository.buscar_por_evento("evt-001")

        self.assertEqual(salvo.alerta_id, "alerta-001")

    def test_buscar_alerta_inexistente(self):
        self.assertIsNone(self.repository.buscar_por_id("x"))
        self.assertIsNone(self.repository.buscar_por_evento("x"))

    def test_rejeitar_id_duplicado(self):
        with self.assertRaises(ValueError):
            self.repository.salvar(novo_alerta(2, alerta_id="alerta-001"))

    def test_rejeitar_evento_duplicado(self):
        with self.assertRaises(ValueError):
            self.repository.salvar(novo_alerta(2, evento_id="evt-001"))

    def test_alerta_de_comando_nao_indexa_evento(self):
        """Alerta criado por comando pode citar um evento já alertado."""

        self.repository.salvar(
            novo_alerta(2, evento_id="evt-001"), indexar_evento=False
        )

        self.assertEqual(
            self.repository.buscar_por_evento("evt-001").alerta_id,
            "alerta-001",
        )

    def test_alterar_copia_nao_altera_repositorio(self):
        """O estado só muda por atualizar(), com histórico."""

        copia = self.repository.buscar_por_id("alerta-001")
        copia.estado = "CLOSED"
        self.alerta.estado = "CLOSED"

        self.assertEqual(
            self.repository.buscar_por_id("alerta-001").estado, "CREATED"
        )


class TestHistoricoRepositorio(unittest.TestCase):

    def setUp(self):
        self.repository = AlertRepository()
        self.repository.salvar(novo_alerta())

    def registro(self, acao="ACKNOWLEDGED", **alteracoes):
        dados = dict(
            alerta_id="alerta-001",
            evento_id="evt-001",
            acao=acao,
            autor_id="user:maria",
        )
        dados.update(alteracoes)
        return RegistroHistorico(**dados)

    def atualizado(self, estado="ACKNOWLEDGED"):
        alerta = self.repository.buscar_por_id("alerta-001")
        alerta.estado = estado
        return alerta

    def test_historico_criado_automaticamente(self):
        """Salvar um alerta deve registrar sua criação."""

        historico = self.repository.buscar_historico("alerta-001")

        self.assertEqual(len(historico), 1)
        self.assertEqual(historico[0].acao, "CREATED")

    def test_atualizar_grava_estado_e_historico(self):
        self.repository.atualizar(self.atualizado(), self.registro())

        self.assertEqual(
            self.repository.buscar_por_id("alerta-001").estado,
            "ACKNOWLEDGED",
        )
        self.assertEqual(
            [r.acao for r in self.repository.buscar_historico("alerta-001")],
            ["CREATED", "ACKNOWLEDGED"],
        )

    def test_registro_deve_ser_o_novo_estado(self):
        with self.assertRaises(ValueError):
            self.repository.atualizar(
                self.atualizado("CLOSED"), self.registro("ACKNOWLEDGED")
            )

    def test_rejeitar_evento_incorreto(self):
        with self.assertRaises(ValueError):
            self.repository.atualizar(
                self.atualizado(), self.registro(evento_id="evt-999")
            )

    def test_rejeitar_alerta_inexistente(self):
        alerta = self.atualizado()
        alerta.alerta_id = "alerta-999"

        with self.assertRaises(ValueError):
            self.repository.atualizar(
                alerta, self.registro(alerta_id="alerta-999")
            )

    def test_rejeitar_registro_duplicado(self):
        registro = self.registro()
        self.repository.atualizar(self.atualizado(), registro)

        with self.assertRaises(ValueError):
            self.repository.atualizar(self.atualizado(), registro)

    def test_rejeitar_criacao_manual(self):
        with self.assertRaises(ValueError):
            self.repository.atualizar(
                self.atualizado("CREATED"), self.registro("CREATED")
            )

    def test_falha_nao_altera_nada(self):
        """Alerta inválido: nem estado nem histórico mudam."""

        alerta = self.atualizado()
        alerta.canais = []

        with self.assertRaises(ValueError):
            self.repository.atualizar(alerta, self.registro())

        self.assertEqual(len(self.repository.buscar_historico("alerta-001")), 1)
        self.assertEqual(
            self.repository.buscar_por_id("alerta-001").estado, "CREATED"
        )


class TestListar(unittest.TestCase):

    def setUp(self):
        self.repository = AlertRepository()

        for numero in range(1, 6):
            self.repository.salvar(
                novo_alerta(
                    numero,
                    severidade="HIGH" if numero % 2 else "LOW",
                )
            )

    def test_ordem_de_criacao(self):
        alertas, proximo = self.repository.listar()

        self.assertEqual(
            [a.alerta_id for a in alertas],
            [f"alerta-{n:03d}" for n in range(1, 6)],
        )
        self.assertIsNone(proximo)

    def test_filtros(self):
        alertas, _ = self.repository.listar(
            desde=datetime(2026, 9, 23, 14, 2, tzinfo=timezone.utc),
            ate=datetime(2026, 9, 23, 14, 5, tzinfo=timezone.utc),
            severidade="HIGH",
        )

        self.assertEqual([a.alerta_id for a in alertas], ["alerta-003"])

    def test_paginacao(self):
        """A próxima página começa no criado_em do primeiro não devolvido."""

        alertas, proximo = self.repository.listar(limite=2)

        self.assertEqual(len(alertas), 2)
        self.assertEqual(
            proximo, datetime(2026, 9, 23, 14, 3, tzinfo=timezone.utc)
        )

        seguinte, _ = self.repository.listar(desde=proximo, limite=2)

        self.assertEqual(seguinte[0].alerta_id, "alerta-003")


class TestMensagensProcessadas(unittest.TestCase):

    def test_registrar_e_consultar(self):
        repository = AlertRepository()

        self.assertFalse(repository.mensagem_processada("m-1"))

        repository.registrar_mensagem("m-1", {"status": "OK"})

        self.assertTrue(repository.mensagem_processada("m-1"))
        self.assertEqual(
            repository.resposta_registrada("m-1"), {"status": "OK"}
        )


if __name__ == "__main__":
    unittest.main()
