"""
Adaptadores Kafka do I9 (barramento B3).

Semântica **at-least-once**: o offset de um quadro do I1 só é confirmado
(commit) depois que o evento `ods.i9.ppe_compliance` correspondente foi aceito
pelo broker. Se o I9 cair no meio, o quadro é reprocessado ao subir; como a
inferência é determinística por quadro, o S2 descarta a duplicata pela chave do
quadro (`source_id`, `session_id`, `frame_index`).

* `KafkaSettings`: configuração lida de variáveis de ambiente (valores do B3);
* `KafkaIngestionAdapter`: consome `ods.i1.detections` (porta de ingestão);
* `KafkaCalibrationAdapter`: lê `ods.i3.calibration` desde o início do tópico
  (idealmente compactado), mantendo a última calibração por `source_id`;
* `KafkaArtifactAdapter`: lê `ods.artifact.published` desde o início e entrega o
  `PPE_CATALOG` mais recente do A5 (baixado e verificado pelo `CatalogLoader`);
* `KafkaPublisherAdapter`: publica `ods.i9.ppe_compliance` com chave
  `source_id`, `acks=all` e produtor idempotente;
* `DeadLetterPublisher`: encaminha mensagens inválidas ao tópico de erros;
* `KafkaI9Service`: laço contínuo que liga tudo ao `I9Pipeline`.

O cliente `confluent_kafka` é importado apenas em `create_*`, para que o resto do
componente (e os testes) continue usando só a biblioteca padrão.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from src.adapters.catalog_adapters import CatalogLoader, RegistryClient
from src.adapters.message_adapters import MessageCalibrationAdapter, decode_message
from src.domain.catalog import ARTIFACT_PUBLISHED_SCHEMA, PpeCatalog
from src.domain.models import (
    CALIBRATION_SCHEMA,
    COMPLIANCE_SCHEMA,
    DETECTIONS_SCHEMA,
    ComplianceEvent,
    DetectionFrame,
)

logger = logging.getLogger("i9.kafka")


def _env(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key, "").strip()
    return value or default


@dataclass(frozen=True)
class KafkaSettings:
    """Parâmetros do barramento. Os defaults são provisórios até o B3 confirmar."""

    bootstrap_servers: str = "localhost:9092"
    group_id: str = "ods-i9"
    detections_topic: str = DETECTIONS_SCHEMA
    calibration_topic: str = CALIBRATION_SCHEMA
    artifacts_topic: str = ARTIFACT_PUBLISHED_SCHEMA
    compliance_topic: str = COMPLIANCE_SCHEMA
    dead_letter_topic: str = "ods.i9.dlq"
    auto_offset_reset: str = "latest"
    poll_timeout_s: float = 1.0
    delivery_timeout_s: float = 10.0
    calibration_warmup_s: float = 3.0
    security_protocol: str = "PLAINTEXT"
    sasl_mechanism: str = ""
    sasl_username: str = ""
    sasl_password: str = ""
    ssl_ca_location: str = ""
    registry_base_url: str = ""
    catalog_owner: str = "A5"

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "KafkaSettings":
        env = os.environ if env is None else env
        default = cls()
        return cls(
            bootstrap_servers=_env(env, "KAFKA_BOOTSTRAP_SERVERS", default.bootstrap_servers),
            group_id=_env(env, "I9_KAFKA_GROUP_ID", default.group_id),
            detections_topic=_env(env, "I9_TOPIC_DETECTIONS", default.detections_topic),
            calibration_topic=_env(env, "I9_TOPIC_CALIBRATION", default.calibration_topic),
            artifacts_topic=_env(env, "I9_TOPIC_ARTIFACTS", default.artifacts_topic),
            compliance_topic=_env(env, "I9_TOPIC_COMPLIANCE", default.compliance_topic),
            # string vazia explícita desliga o DLQ
            dead_letter_topic=env.get("I9_TOPIC_DLQ", default.dead_letter_topic).strip(),
            auto_offset_reset=_env(env, "I9_AUTO_OFFSET_RESET", default.auto_offset_reset),
            poll_timeout_s=float(_env(env, "I9_POLL_TIMEOUT_S", str(default.poll_timeout_s))),
            delivery_timeout_s=float(_env(env, "I9_DELIVERY_TIMEOUT_S", str(default.delivery_timeout_s))),
            calibration_warmup_s=float(
                _env(env, "I9_CALIBRATION_WARMUP_S", str(default.calibration_warmup_s))
            ),
            security_protocol=_env(env, "KAFKA_SECURITY_PROTOCOL", default.security_protocol),
            sasl_mechanism=_env(env, "KAFKA_SASL_MECHANISM", ""),
            sasl_username=_env(env, "KAFKA_SASL_USERNAME", ""),
            sasl_password=_env(env, "KAFKA_SASL_PASSWORD", ""),
            ssl_ca_location=_env(env, "KAFKA_SSL_CA_LOCATION", ""),
            registry_base_url=_env(env, "A5_REGISTRY_BASE_URL", ""),
            catalog_owner=env.get("I9_CATALOG_OWNER", default.catalog_owner).strip(),
        )

    def _common_config(self) -> Dict[str, Any]:
        config: Dict[str, Any] = {
            "bootstrap.servers": self.bootstrap_servers,
            "client.id": "ods-i9",
            "security.protocol": self.security_protocol,
        }
        if self.sasl_mechanism:
            config["sasl.mechanism"] = self.sasl_mechanism
            config["sasl.username"] = self.sasl_username
            config["sasl.password"] = self.sasl_password
        if self.ssl_ca_location:
            config["ssl.ca.location"] = self.ssl_ca_location
        return config

    def detections_consumer_config(self) -> Dict[str, Any]:
        return {
            **self._common_config(),
            "group.id": self.group_id,
            "auto.offset.reset": self.auto_offset_reset,
            # commit manual: só depois que a saída do quadro foi entregue
            "enable.auto.commit": False,
        }

    def calibration_consumer_config(self) -> Dict[str, Any]:
        return {
            **self._common_config(),
            # grupo próprio e sem commit: a cada início o tópico é relido inteiro
            "group.id": f"{self.group_id}.calibration",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }

    def artifacts_consumer_config(self) -> Dict[str, Any]:
        return {
            **self.calibration_consumer_config(),
            "group.id": f"{self.group_id}.artifacts",
        }

    def producer_config(self) -> Dict[str, Any]:
        return {
            **self._common_config(),
            "acks": "all",
            "enable.idempotence": True,
        }


def create_consumer(config: Dict[str, Any]):
    from confluent_kafka import Consumer

    return Consumer(config)


def create_producer(config: Dict[str, Any]):
    from confluent_kafka import Producer

    return Producer(config)


def _rewind_to_beginning(consumer, partitions) -> None:
    """Callback `on_assign`: relê o tópico de calibração desde o primeiro offset."""
    from confluent_kafka import OFFSET_BEGINNING

    for partition in partitions:
        partition.offset = OFFSET_BEGINNING
    consumer.assign(partitions)


def _is_fatal(error) -> bool:
    fatal = getattr(error, "fatal", None)
    return bool(fatal()) if callable(fatal) else False


class DeliveryError(RuntimeError):
    """O broker não confirmou a entrega de uma ou mais mensagens."""


class KafkaPublisherAdapter:
    """Porta de saída: publica `ods.i9.ppe_compliance` e confirma a entrega."""

    def __init__(self, producer, topic: str = COMPLIANCE_SCHEMA, delivery_timeout_s: float = 10.0):
        self._producer = producer
        self.topic = topic
        self.delivery_timeout_s = delivery_timeout_s
        self._errors: List[str] = []

    def publish_event(self, event: ComplianceEvent) -> None:
        for body in event.messages():
            self._producer.produce(
                self.topic,
                key=event.source_id.encode("utf-8"),
                value=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers=[
                    ("schema", body["schema"].encode("utf-8")),
                    ("message_id", body["message_id"].encode("utf-8")),
                ],
                on_delivery=self._on_delivery,
            )
        self._producer.poll(0)

    def flush(self) -> None:
        """Espera o broker confirmar tudo o que foi produzido; falha se algo se perdeu."""
        pending = self._producer.flush(self.delivery_timeout_s)
        errors, self._errors = self._errors, []
        if pending:
            errors.append(f"{pending} mensagem(ns) sem confirmação após {self.delivery_timeout_s}s")
        if errors:
            raise DeliveryError("; ".join(errors))

    def _on_delivery(self, error, message) -> None:
        if error is not None:
            self._errors.append(str(error))


class DeadLetterPublisher:
    """Encaminha mensagens rejeitadas ao tópico de erros, com o motivo nos headers."""

    def __init__(self, producer, topic: str):
        self._producer = producer
        self.topic = topic

    def send(self, message, reason: str) -> None:
        headers = [
            ("error", reason.encode("utf-8")),
            ("source_topic", str(message.topic()).encode("utf-8")),
            ("source_partition", str(message.partition()).encode("utf-8")),
            ("source_offset", str(message.offset()).encode("utf-8")),
        ]
        self._producer.produce(self.topic, key=message.key(), value=message.value(), headers=headers)
        self._producer.poll(0)


class KafkaIngestionAdapter:
    """Porta de ingestão: consome `ods.i1.detections` com commit manual.

    `get_next_event` devolve o próximo quadro válido ou None quando não chegou
    nada dentro do `poll_timeout_s`. Depois de publicar a saída, quem orquestra
    chama `commit()` para confirmar o offset do quadro.
    """

    def __init__(
        self,
        consumer,
        topic: str = DETECTIONS_SCHEMA,
        poll_timeout_s: float = 1.0,
        dead_letters: Optional[DeadLetterPublisher] = None,
    ):
        self._consumer = consumer
        self.topic = topic
        self.poll_timeout_s = poll_timeout_s
        self._dead_letters = dead_letters
        self._pending = None
        self.rejected: List[Tuple[Any, str]] = []
        self._consumer.subscribe([topic])

    def get_next_event(self) -> Optional[DetectionFrame]:
        message = self._consumer.poll(self.poll_timeout_s)
        if message is None:
            return None
        error = message.error()
        if error is not None:
            if _is_fatal(error):
                raise RuntimeError(f"erro fatal do consumidor Kafka: {error}")
            logger.warning("erro do consumidor em %s: %s", self.topic, error)
            return None

        try:
            frame = DetectionFrame.from_event(decode_message(message.value()))
        except (ValueError, UnicodeDecodeError) as exc:
            self._reject(message, str(exc))
            return None

        self._pending = message
        return frame

    def commit(self) -> None:
        """Confirma o offset do último quadro devolvido (após a saída ser entregue)."""
        if self._pending is None:
            return
        self._consumer.commit(message=self._pending, asynchronous=False)
        self._pending = None

    def close(self) -> None:
        self._consumer.close()

    def _reject(self, message, reason: str) -> None:
        logger.warning(
            "mensagem rejeitada %s[%s]@%s: %s",
            message.topic(), message.partition(), message.offset(), reason,
        )
        self.rejected.append((message.value(), reason))
        if self._dead_letters is not None:
            self._dead_letters.send(message, reason)
        # mensagem inválida não volta a ser processada
        self._consumer.commit(message=message, asynchronous=False)


class KafkaCalibrationAdapter:
    """Porta de calibração alimentada pelo tópico `ods.i3.calibration`."""

    def __init__(self, consumer, topic: str = CALIBRATION_SCHEMA, on_assign: Optional[Callable] = None):
        self._consumer = consumer
        self.topic = topic
        self._store = MessageCalibrationAdapter()
        if on_assign is None:
            self._consumer.subscribe([topic])
        else:
            self._consumer.subscribe([topic], on_assign=on_assign)

    @property
    def rejected(self) -> List[Tuple[Any, str]]:
        return self._store.rejected

    def drain(self, max_messages: int = 500, timeout_s: float = 0.0) -> int:
        """Consome as calibrações disponíveis sem bloquear o processamento de quadros."""
        lidas = 0
        while lidas < max_messages:
            message = self._consumer.poll(timeout_s)
            if message is None:
                break
            if message.error() is not None:
                logger.warning("erro do consumidor em %s: %s", self.topic, message.error())
                continue
            calibration = self._store.on_message(message.value())
            if calibration is not None:
                logger.info(
                    "calibração %s recebida para %s",
                    calibration.calibration_version, calibration.source_id,
                )
            lidas += 1
        return lidas

    def warm_up(self, duration_s: float) -> int:
        """Lê o histórico compactado na partida, até o tópico ficar quieto."""
        deadline = time.monotonic() + duration_s
        total = 0
        while time.monotonic() < deadline:
            total += self.drain(timeout_s=0.5)
        return total

    def get_calibration(self, source_id: str):
        return self._store.get_calibration(source_id)

    def close(self) -> None:
        self._consumer.close()


class KafkaArtifactAdapter:
    """Acompanha `ods.artifact.published` e devolve o `PPE_CATALOG` mais recente."""

    def __init__(self, consumer, loader: CatalogLoader, topic: str = ARTIFACT_PUBLISHED_SCHEMA,
                 on_assign: Optional[Callable] = None):
        self._consumer = consumer
        self.loader = loader
        self.topic = topic
        if on_assign is None:
            self._consumer.subscribe([topic])
        else:
            self._consumer.subscribe([topic], on_assign=on_assign)

    def drain(self, max_messages: int = 100, timeout_s: float = 0.0) -> Optional[PpeCatalog]:
        """Consome os anúncios disponíveis; devolve o último catálogo válido (ou None)."""
        ultimo: Optional[PpeCatalog] = None
        for _ in range(max_messages):
            message = self._consumer.poll(timeout_s)
            if message is None:
                break
            if message.error() is not None:
                logger.warning("erro do consumidor em %s: %s", self.topic, message.error())
                continue
            catalog = self.loader.on_message(message.value())
            if catalog is not None:
                ultimo = catalog
        return ultimo

    def warm_up(self, duration_s: float) -> Optional[PpeCatalog]:
        deadline = time.monotonic() + duration_s
        ultimo = None
        while time.monotonic() < deadline:
            ultimo = self.drain(timeout_s=0.5) or ultimo
        return ultimo

    def close(self) -> None:
        self._consumer.close()


class KafkaI9Service:
    """Laço contínuo do I9 sobre o barramento.

    Para cada quadro: atualiza calibrações, processa, espera a confirmação da
    publicação e só então confirma o offset do I1. Uma falha de entrega
    interrompe o serviço sem confirmar o offset, para o quadro ser reprocessado.
    """

    def __init__(self, pipeline, ingestion: KafkaIngestionAdapter, calibration: KafkaCalibrationAdapter,
                 publisher: KafkaPublisherAdapter, artifacts: Optional[KafkaArtifactAdapter] = None):
        self.pipeline = pipeline
        self.ingestion = ingestion
        self.calibration = calibration
        self.publisher = publisher
        self.artifacts = artifacts
        self.processed = 0
        self._running = False

    def stop(self, *_args) -> None:
        self._running = False

    def run(self, max_frames: Optional[int] = None, warmup_s: float = 0.0) -> int:
        self._running = True
        try:
            if warmup_s > 0:
                lidas = self.calibration.warm_up(warmup_s)
                logger.info("%d calibração(ões) lida(s) na partida", lidas)
                if self.artifacts is not None:
                    self._apply_catalog(self.artifacts.warm_up(warmup_s))
            while self._running and (max_frames is None or self.processed < max_frames):
                self.calibration.drain()
                if self.artifacts is not None:
                    self._apply_catalog(self.artifacts.drain())
                frame = self.ingestion.get_next_event()
                if frame is None:
                    continue
                self.pipeline.process(frame)
                self.publisher.flush()
                self.ingestion.commit()
                self.processed += 1
        finally:
            self.close()
        return self.processed

    def _apply_catalog(self, catalog: Optional[PpeCatalog]) -> None:
        if catalog is None:
            return
        try:
            policy = self.pipeline.apply_catalog(catalog)
        except ValueError as exc:
            logger.error("PPE_CATALOG %s rejeitado: %s", catalog.artifact_version, exc)
            return
        logger.info(
            "PPE_CATALOG %s em uso: avaliando %s%s",
            catalog.artifact_version,
            ", ".join(policy.class_order),
            f" (sem zona do corpo no I9: {', '.join(policy.unsupported_items)})"
            if policy.unsupported_items else "",
        )

    def close(self) -> None:
        closers = [self.ingestion.close, self.calibration.close]
        if self.artifacts is not None:
            closers.append(self.artifacts.close)
        for close in closers:
            try:
                close()
            except Exception:  # noqa: BLE001 - encerramento não deve mascarar o erro original
                logger.exception("falha ao fechar consumidor")
        try:
            self.publisher.flush()
        except DeliveryError:
            logger.exception("mensagens pendentes no encerramento")


def build_kafka_service(build_pipeline: Callable[..., Any], settings: Optional[KafkaSettings] = None) -> KafkaI9Service:
    """Monta o serviço com clientes `confluent_kafka` reais a partir das configurações."""
    settings = settings or KafkaSettings.from_env()
    producer = create_producer(settings.producer_config())

    dead_letters = (
        DeadLetterPublisher(producer, settings.dead_letter_topic) if settings.dead_letter_topic else None
    )
    ingestion = KafkaIngestionAdapter(
        create_consumer(settings.detections_consumer_config()),
        settings.detections_topic,
        settings.poll_timeout_s,
        dead_letters,
    )
    calibration = KafkaCalibrationAdapter(
        create_consumer(settings.calibration_consumer_config()),
        settings.calibration_topic,
        on_assign=_rewind_to_beginning,
    )
    artifacts = KafkaArtifactAdapter(
        create_consumer(settings.artifacts_consumer_config()),
        CatalogLoader(RegistryClient(settings.registry_base_url), settings.catalog_owner),
        settings.artifacts_topic,
        on_assign=_rewind_to_beginning,
    )
    publisher = KafkaPublisherAdapter(producer, settings.compliance_topic, settings.delivery_timeout_s)

    pipeline = build_pipeline(ingestion=ingestion, calibration=calibration, output=publisher)
    return KafkaI9Service(pipeline, ingestion, calibration, publisher, artifacts)


def install_signal_handlers(service: KafkaI9Service) -> None:
    """SIGINT/SIGTERM encerram o laço de forma limpa (commit e flush pendentes)."""
    signal.signal(signal.SIGINT, service.stop)
    signal.signal(signal.SIGTERM, service.stop)
