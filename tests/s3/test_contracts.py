
import unittest

from s3.contracts import EventoQualificado
from s3.errors import INVALID_PAYLOAD, ErroS3

from fabricas import evento, mensagem_evento


class TestEventoQualificado(unittest.TestCase):

    def test_evento_valido(self):
        """Um evento válido deve ser aceito."""

        evento().validar()

    def test_confianca_invalida(self):
        """Confiança fora de 0 a 1 deve ser rejeitada."""

        for valor in (1.5, -0.1):
            with self.subTest(valor=valor):
                with self.assertRaises(ErroS3):
                    evento(confianca=valor).validar()

    def test_confianca_nao_numerica(self):
        for valor in ("0.9", True, None):
            with self.subTest(valor=valor):
                with self.assertRaises(ErroS3):
                    evento(confianca=valor).validar()

    def test_horario_invalido(self):
        """started_at precisa ser ISO 8601 com fuso."""

        for valor in ("qualquer coisa", "2026-09-23T14:29:52"):
            with self.subTest(valor=valor):
                with self.assertRaises(ErroS3):
                    evento(iniciado_em=valor).validar()

    def test_status_e_fase_invalidos(self):
        with self.assertRaises(ErroS3):
            evento(status="TALVEZ").validar()

        with self.assertRaises(ErroS3):
            evento(fase="PAUSED").validar()

    def test_campos_vazios(self):
        for campo in ("evento_id", "tipo", "zona_id", "equipamento"):
            with self.subTest(campo=campo):
                with self.assertRaises(ErroS3):
                    evento(**{campo: "  "}).validar()

    def test_duracao_negativa(self):
        with self.assertRaises(ErroS3):
            evento(duracao_ms=-1).validar()


class TestDeMensagem(unittest.TestCase):

    def test_mapeia_campos_do_contrato(self):
        """Os campos de ods.s2.event viram os campos internos."""

        recebido = EventoQualificado.de_mensagem(mensagem_evento())

        self.assertEqual(recebido.evento_id, "6d9f2b1c-3e4a-4b5c-8d6e-7f8a9b0c1d2e")
        self.assertEqual(recebido.tipo, "PPE_NON_COMPLIANT")
        self.assertEqual(recebido.regra_id, "a5-luva-galpao")
        self.assertEqual(recebido.entidade_id, "e-7a21")
        self.assertEqual(recebido.classe, "person")
        self.assertEqual(recebido.equipamento, "luva")
        self.assertEqual(recebido.duracao_ms, 8000)
        self.assertEqual(recebido.detalhes["compliance"], "ABSENT")
        self.assertEqual(recebido.origem, "cam0")
        self.assertEqual(recebido.capturado_em, "2026-09-23T14:29:59.870Z")

    def test_campo_obrigatorio_ausente(self):
        """Todos os campos obrigatórios do payload são exigidos."""

        for campo in (
            "event_id", "event_type", "rule_id", "status", "phase",
            "confidence", "started_at", "duration_ms", "source_ids",
        ):
            with self.subTest(campo=campo):
                dados = mensagem_evento()
                del dados["payload"][campo]

                with self.assertRaises(ErroS3) as contexto:
                    EventoQualificado.de_mensagem(dados)

                self.assertEqual(contexto.exception.codigo, INVALID_PAYLOAD)

    def test_opcionais_ausentes(self):
        """entity_id, class, zone_id, equipment_item e details são opcionais."""

        dados = mensagem_evento()

        for campo in ("entity_id", "class", "zone_id", "equipment_item", "details"):
            del dados["payload"][campo]

        recebido = EventoQualificado.de_mensagem(dados)

        self.assertIsNone(recebido.zona_id)
        self.assertEqual(recebido.detalhes, {})


if __name__ == "__main__":
    unittest.main()
