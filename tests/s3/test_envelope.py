
import unittest
from datetime import datetime, timedelta, timezone

from s3.envelope import (
    PERFIL_CMD,
    PERFIL_EV_SERVICO,
    Sequencia,
    decodificar,
    formatar_horario,
    ler_horario,
    montar_envelope,
    validar_envelope,
)
from s3.errors import INVALID_MESSAGE, ErroS3

from fabricas import mensagem_evento


class TestHorarios(unittest.TestCase):

    def test_formato_com_milissegundos(self):
        """Saída em UTC com milissegundos e Z."""

        brasilia = timezone(timedelta(hours=-3))
        horario = datetime(2026, 9, 23, 11, 29, 59, 870000, tzinfo=brasilia)

        self.assertEqual(
            formatar_horario(horario),
            "2026-09-23T14:29:59.870Z"
        )

    def test_horario_sem_fuso(self):
        with self.assertRaises(ValueError):
            formatar_horario(datetime(2026, 9, 23, 14, 0, 0))

    def test_ler_horario_valido(self):
        horario = ler_horario("2026-09-23T14:29:59.870Z", "campo")

        self.assertEqual(horario.utcoffset(), timedelta(0))
        self.assertEqual(horario.microsecond, 870000)

    def test_ler_horario_invalido(self):
        """Texto que não é ISO 8601 é rejeitado."""

        for valor in ("qualquer coisa", "", None, 123):
            with self.assertRaises(ErroS3):
                ler_horario(valor, "campo")

    def test_ler_horario_sem_fuso(self):
        with self.assertRaises(ErroS3):
            ler_horario("2026-09-23T14:29:59", "campo")


class TestDecodificar(unittest.TestCase):

    def test_aceita_bytes(self):
        """O Kafka entrega bytes."""

        self.assertEqual(decodificar(b'{"a": 1}'), {"a": 1})

    def test_json_malformado(self):
        with self.assertRaises(ErroS3) as contexto:
            decodificar('{"a":')

        self.assertEqual(contexto.exception.codigo, INVALID_MESSAGE)

    def test_json_nao_objeto(self):
        with self.assertRaises(ErroS3):
            decodificar("[1, 2]")


class TestValidarEnvelope(unittest.TestCase):

    def setUp(self):
        self.dados = mensagem_evento()

    def validar(self):
        return validar_envelope(
            self.dados, "ods.s2.event", "event", PERFIL_EV_SERVICO
        )

    def test_envelope_valido(self):
        payload = self.validar()

        self.assertEqual(payload["event_type"], "PPE_NON_COMPLIANT")

    def test_campo_fixo_ausente(self):
        for campo in ("message_id", "producer", "published_at", "payload"):
            with self.subTest(campo=campo):
                self.dados = mensagem_evento()
                del self.dados[campo]

                with self.assertRaises(ErroS3):
                    self.validar()

    def test_campo_do_perfil_ausente(self):
        """EV-SERVIÇO exige captured_at, session_id e sequence."""

        for campo in PERFIL_EV_SERVICO:
            with self.subTest(campo=campo):
                self.dados = mensagem_evento()
                del self.dados[campo]

                with self.assertRaises(ErroS3):
                    self.validar()

    def test_schema_inesperado(self):
        self.dados["schema"] = "ods.s3.alert"

        with self.assertRaises(ErroS3):
            self.validar()

    def test_message_type_inesperado(self):
        self.dados["message_type"] = "command"

        with self.assertRaises(ErroS3):
            self.validar()

    def test_minor_aceito_major_rejeitado(self):
        """1.x é aceito; 2.0 não."""

        self.dados["schema_version"] = "1.3"
        self.validar()

        self.dados["schema_version"] = "2.0"

        with self.assertRaises(ErroS3):
            self.validar()

    def test_sequence_invalido(self):
        for valor in (-1, "3", True):
            with self.subTest(valor=valor):
                self.dados["sequence"] = valor

                with self.assertRaises(ErroS3):
                    self.validar()

    def test_payload_nao_objeto(self):
        self.dados["payload"] = ["evento"]

        with self.assertRaises(ErroS3):
            self.validar()

    def test_perfil_cmd_exige_target(self):
        self.dados["message_type"] = "command"

        with self.assertRaises(ErroS3):
            validar_envelope(self.dados, "ods.s2.event", "command", PERFIL_CMD)


class TestMontarEnvelope(unittest.TestCase):

    def test_campos_fixos_e_contexto(self):
        envelope = montar_envelope(
            "reply", "ods.s3.alert.reply", {"status": "OK"},
            correlation_id="c-1",
        )

        self.assertEqual(envelope["producer"], "S3")
        self.assertEqual(envelope["schema_version"], "1.0")
        self.assertEqual(envelope["correlation_id"], "c-1")
        self.assertTrue(envelope["message_id"])
        self.assertNotIn("session_id", envelope)

    def test_message_ids_diferentes(self):
        primeiro = montar_envelope("event", "x", {})
        segundo = montar_envelope("event", "x", {})

        self.assertNotEqual(primeiro["message_id"], segundo["message_id"])


class TestSequencia(unittest.TestCase):

    def test_contador_por_sessao(self):
        sequencia = Sequencia()

        self.assertEqual(sequencia.proximo("a"), 0)
        self.assertEqual(sequencia.proximo("a"), 1)
        self.assertEqual(sequencia.proximo("b"), 0)
        self.assertEqual(sequencia.proximo(None), 0)


if __name__ == "__main__":
    unittest.main()
