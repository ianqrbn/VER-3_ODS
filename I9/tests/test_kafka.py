"""Testes dos adaptadores Kafka com clientes falsos (mesma interface do confluent_kafka)."""

from __future__ import annotations

import json
import unittest

from tests.helpers import ROOT, quiet
import main as app
from src.adapters.kafka_adapters import (
    DeadLetterPublisher,
    DeliveryError,
    KafkaCalibrationAdapter,
    KafkaI9Service,
    KafkaIngestionAdapter,
    KafkaPublisherAdapter,
    KafkaSettings,
)

EXAMPLE_I1 = json.loads((ROOT / "examples" / "i1_detections.json").read_text(encoding="utf-8"))
EXAMPLE_I3 = json.loads((ROOT / "examples" / "i3_calibration.json").read_text(encoding="utf-8"))


class FakeError:
    def __init__(self, text: str, fatal: bool = False):
        self._text = text
        self._fatal = fatal

    def fatal(self) -> bool:
        return self._fatal

    def __str__(self) -> str:
        return self._text


class FakeMessage:
    def __init__(self, value, topic="t", offset=0, key=b"cam0", error=None):
        if isinstance(value, dict):
            value = json.dumps(value).encode("utf-8")
        elif isinstance(value, str):
            value = value.encode("utf-8")
        self._value = value
        self._topic = topic
        self._offset = offset
        self._key = key
        self._error = error

    def value(self):
        return self._value

    def key(self):
        return self._key

    def topic(self):
        return self._topic

    def partition(self):
        return 0

    def offset(self):
        return self._offset

    def error(self):
        return self._error


class FakeConsumer:
    def __init__(self, messages=()):
        self.queue = list(messages)
        self.subscribed = []
        self.on_assign = None
        self.commits = []
        self.closed = False

    def subscribe(self, topics, on_assign=None):
        self.subscribed = topics
        self.on_assign = on_assign

    def poll(self, timeout=None):
        return self.queue.pop(0) if self.queue else None

    def commit(self, message=None, asynchronous=True):
        self.commits.append(message.offset())

    def close(self):
        self.closed = True


class FakeProducer:
    def __init__(self, fail_with=None, pending=0):
        self.produced = []
        self._callbacks = []
        self.fail_with = fail_with
        self.pending = pending

    def produce(self, topic, key=None, value=None, headers=None, on_delivery=None):
        self.produced.append({"topic": topic, "key": key, "value": value, "headers": dict(headers or [])})
        if on_delivery:
            self._callbacks.append(on_delivery)

    def poll(self, timeout=0):
        return 0

    def flush(self, timeout=None):
        callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            callback(self.fail_with, None)
        return self.pending


def i1_message(offset: int, sequence: int = 42) -> FakeMessage:
    body = json.loads(json.dumps(EXAMPLE_I1))
    body["sequence"] = sequence
    body["payload"]["frame_index"] = sequence
    return FakeMessage(body, topic="ods.i1.detections", offset=offset)


def build_service(detections, calibrations=(), producer=None, dlq=True):
    producer = producer or FakeProducer()
    det_consumer = FakeConsumer(detections)
    cal_consumer = FakeConsumer(calibrations)
    ingestion = KafkaIngestionAdapter(
        det_consumer,
        dead_letters=DeadLetterPublisher(producer, "ods.i9.dlq") if dlq else None,
    )
    calibration = KafkaCalibrationAdapter(cal_consumer)
    publisher = KafkaPublisherAdapter(producer)
    pipeline = app.build_pipeline(ingestion=ingestion, calibration=calibration, output=publisher)
    service = KafkaI9Service(pipeline, ingestion, calibration, publisher)
    return service, producer, det_consumer, cal_consumer


def outputs(producer, topic="ods.i9.ppe_compliance"):
    return [p for p in producer.produced if p["topic"] == topic]


class SettingsTest(unittest.TestCase):
    def test_defaults_usam_os_nomes_dos_schemas(self):
        settings = KafkaSettings.from_env({})
        self.assertEqual(settings.detections_topic, "ods.i1.detections")
        self.assertEqual(settings.calibration_topic, "ods.i3.calibration")
        self.assertEqual(settings.compliance_topic, "ods.i9.ppe_compliance")
        self.assertEqual(settings.bootstrap_servers, "localhost:9092")

    def test_variaveis_de_ambiente_sobrescrevem(self):
        settings = KafkaSettings.from_env(
            {
                "KAFKA_BOOTSTRAP_SERVERS": "b3:9093",
                "I9_KAFKA_GROUP_ID": "grupo-x",
                "I9_TOPIC_DLQ": "",
                "KAFKA_SECURITY_PROTOCOL": "SASL_SSL",
                "KAFKA_SASL_MECHANISM": "PLAIN",
                "KAFKA_SASL_USERNAME": "i9",
                "KAFKA_SASL_PASSWORD": "segredo",
            }
        )
        self.assertEqual(settings.dead_letter_topic, "")
        consumer = settings.detections_consumer_config()
        self.assertEqual(consumer["bootstrap.servers"], "b3:9093")
        self.assertEqual(consumer["group.id"], "grupo-x")
        self.assertEqual(consumer["sasl.username"], "i9")
        self.assertEqual(consumer["security.protocol"], "SASL_SSL")

    def test_commit_manual_e_produtor_idempotente(self):
        settings = KafkaSettings.from_env({})
        self.assertFalse(settings.detections_consumer_config()["enable.auto.commit"])
        self.assertEqual(settings.calibration_consumer_config()["auto.offset.reset"], "earliest")
        self.assertNotEqual(
            settings.calibration_consumer_config()["group.id"],
            settings.detections_consumer_config()["group.id"],
        )
        producer = settings.producer_config()
        self.assertEqual(producer["acks"], "all")
        self.assertTrue(producer["enable.idempotence"])


class ServiceTest(unittest.TestCase):
    def test_quadro_e_publicado_e_so_depois_confirmado(self):
        service, producer, consumer, _ = build_service([i1_message(7)])
        self.assertEqual(service.run(max_frames=1), 1)

        saidas = outputs(producer)
        self.assertEqual(len(saidas), 1)
        self.assertEqual(saidas[0]["key"], b"cam0")
        body = json.loads(saidas[0]["value"])
        self.assertEqual(body["schema"], "ods.i9.ppe_compliance")
        self.assertEqual(body["sequence"], 42)
        self.assertEqual(saidas[0]["headers"]["message_id"], body["message_id"].encode())
        self.assertEqual(consumer.commits, [7])
        self.assertTrue(consumer.closed)

    def test_falha_de_entrega_nao_confirma_o_offset(self):
        producer = FakeProducer(fail_with=FakeError("broker indisponível"))
        service, _, consumer, _ = build_service([i1_message(3)], producer=producer)
        with self.assertRaises(DeliveryError):
            service.run(max_frames=1)
        self.assertEqual(consumer.commits, [])
        self.assertTrue(consumer.closed)

    def test_mensagem_sem_confirmacao_no_prazo_e_falha(self):
        service, _, consumer, _ = build_service([i1_message(3)], producer=FakeProducer(pending=1))
        # o encerramento também tenta o flush e registra o que continua pendente
        with self.assertRaises(DeliveryError), self.assertLogs("i9.kafka", level="ERROR"):
            service.run(max_frames=1)
        self.assertEqual(consumer.commits, [])

    def test_mensagem_invalida_vai_para_dlq_e_nao_trava_o_consumo(self):
        invalida = FakeMessage("{nao e json", topic="ods.i1.detections", offset=1)
        service, producer, consumer, _ = build_service([invalida, i1_message(2)])
        self.assertEqual(service.run(max_frames=1), 1)

        dlq = outputs(producer, "ods.i9.dlq")
        self.assertEqual(len(dlq), 1)
        self.assertEqual(dlq[0]["value"], b"{nao e json")
        self.assertEqual(dlq[0]["headers"]["source_offset"], b"1")
        self.assertIn("error", dlq[0]["headers"])
        self.assertEqual(consumer.commits, [1, 2])
        self.assertEqual(len(outputs(producer)), 1)

    def test_sem_dlq_a_mensagem_invalida_e_so_registrada(self):
        invalida = FakeMessage(dict(EXAMPLE_I1, schema="outro"), offset=1)
        service, producer, consumer, _ = build_service([invalida, i1_message(2)], dlq=False)
        service.run(max_frames=1)
        self.assertEqual(outputs(producer, "ods.i9.dlq"), [])
        self.assertEqual(len(service.ingestion.rejected), 1)
        self.assertEqual(consumer.commits, [1, 2])

    def test_erro_transitorio_do_consumidor_e_ignorado(self):
        erro = FakeMessage(b"", error=FakeError("timeout de rede"))
        service, _, consumer, _ = build_service([erro, i1_message(5)])
        with self.assertLogs("i9.kafka", level="WARNING"):
            self.assertEqual(service.run(max_frames=1), 1)
        self.assertEqual(consumer.commits, [5])

    def test_erro_fatal_do_consumidor_interrompe(self):
        erro = FakeMessage(b"", error=FakeError("credenciais inválidas", fatal=True))
        service, _, consumer, _ = build_service([erro])
        with self.assertRaises(RuntimeError):
            service.run(max_frames=1)
        self.assertTrue(consumer.closed)

    def test_calibracao_do_topico_e_usada_no_quadro(self):
        calibracao = FakeMessage(EXAMPLE_I3, topic="ods.i3.calibration")
        service, producer, _, _ = build_service([i1_message(1)], calibrations=[calibracao])
        service.run(max_frames=1)
        body = json.loads(outputs(producer)[0]["value"])
        self.assertEqual(body["payload"]["calibration_status"], "valid")
        self.assertEqual(body["payload"]["calibration_version"], "cam0-v1")

    def test_stop_encerra_o_laco(self):
        service, _, consumer, _ = build_service([i1_message(1), i1_message(2)])
        original = service.pipeline.process

        def processa_e_para(frame):
            service.stop()
            return original(frame)

        service.pipeline.process = processa_e_para
        with quiet():
            self.assertEqual(service.run(), 1)
        self.assertEqual(consumer.commits, [1])


if __name__ == "__main__":
    unittest.main()
