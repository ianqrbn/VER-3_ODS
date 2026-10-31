"""
Utilitário para testar o I9 no Kafka sem os demais componentes.

    # envia mensagens de um arquivo (JSON, lista JSON ou JSONL); tópico = campo `schema`
    python3 tools/kafka_cli.py send examples/i1_detections.json
    python3 tools/kafka_cli.py send examples/i3_calibration.json

    # acompanha a saída do I9
    python3 tools/kafka_cli.py tail ods.i9.ppe_compliance

A chave de cada mensagem é o `source_id` do envelope. O broker vem de
`KAFKA_BOOTSTRAP_SERVERS` (padrão localhost:9092).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from main import read_messages  # noqa: E402
from src.adapters.kafka_adapters import KafkaSettings, create_consumer, create_producer  # noqa: E402


def send(path: str, topic: str | None, settings: KafkaSettings) -> None:
    producer = create_producer(settings.producer_config())
    erros = []
    for message in read_messages(path):
        destino = topic or message["schema"]
        producer.produce(
            destino,
            key=str(message.get("source_id", "")).encode("utf-8"),
            value=json.dumps(message, ensure_ascii=False).encode("utf-8"),
            on_delivery=lambda err, msg: erros.append(err) if err else None,
        )
        print(f"-> {destino} ({message.get('source_id')}, message_id={message.get('message_id')})")
    producer.flush(10)
    if erros:
        raise SystemExit(f"falha de entrega: {erros}")


def tail(topic: str, settings: KafkaSettings) -> None:
    config = settings.detections_consumer_config()
    config.update({"group.id": f"i9-tail-{uuid.uuid4()}", "auto.offset.reset": "earliest"})
    consumer = create_consumer(config)
    consumer.subscribe([topic])
    try:
        while True:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                print(f"erro: {message.error()}", file=sys.stderr)
                continue
            body = json.loads(message.value())
            print(json.dumps(body, ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Envia/lê mensagens do I9 no Kafka")
    sub = parser.add_subparsers(dest="command", required=True)
    p_send = sub.add_parser("send", help="publica mensagens de um arquivo")
    p_send.add_argument("path")
    p_send.add_argument("--topic", help="tópico de destino (padrão: campo `schema` de cada mensagem)")
    p_tail = sub.add_parser("tail", help="imprime as mensagens de um tópico")
    p_tail.add_argument("topic", nargs="?", default="ods.i9.ppe_compliance")
    args = parser.parse_args()

    settings = KafkaSettings.from_env()
    if args.command == "send":
        send(args.path, args.topic, settings)
    else:
        tail(args.topic, settings)


if __name__ == "__main__":
    main()
