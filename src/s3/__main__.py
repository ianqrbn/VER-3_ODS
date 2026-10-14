"""
Executa o S3 ligado ao Kafka.

    PowerShell:
        $env:PYTHONPATH = "src"
        $env:S3_KAFKA_BOOTSTRAP = "host:porta"
        python -m s3 --routing jsons/routing_a5.json --tempo-limite 60

O broker de testes é pago e compartilhado: use sempre
--tempo-limite ou --max-mensagens (Guia do Kafka, 4.5).
"""

import argparse
import json
import logging

from s3.commands import ProcessadorComandos
from s3.ingestion import IngestorEventos
from s3.kafka_adapter import AssinanteKafka, PublicadorKafka
from s3.routing import RoteadorAlertas
from s3.service import AlertService
from s3.subscription import (
    ConectorComandos,
    ConectorEventos,
    DespachanteS3,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="S3 — Alertas e notificações")
    parser.add_argument(
        "--routing", required=True,
        help="Arquivo JSON com o conteúdo do artefato ROUTING",
    )
    parser.add_argument(
        "--versao-routing",
        help="artifact_version do ROUTING (padrão: nome do arquivo)",
    )
    parser.add_argument("--max-mensagens", type=int)
    parser.add_argument("--tempo-limite", type=float)
    argumentos = parser.parse_args()

    if argumentos.max_mensagens is None and argumentos.tempo_limite is None:
        parser.error("Informe --max-mensagens ou --tempo-limite.")

    logging.basicConfig(level=logging.INFO)

    with open(argumentos.routing, encoding="utf-8") as arquivo:
        conteudo = json.load(arquivo)

    versao = argumentos.versao_routing or argumentos.routing
    roteador = RoteadorAlertas.de_artefato(conteudo, versao)

    publicador = PublicadorKafka()
    service = AlertService(roteador=roteador, publicador=publicador)

    assinante = AssinanteKafka()
    DespachanteS3(
        ConectorEventos(assinante, IngestorEventos(service)),
        ConectorComandos(assinante, ProcessadorComandos(service), publicador),
    ).conectar(assinante)

    entregues = assinante.executar(
        max_mensagens=argumentos.max_mensagens,
        tempo_limite_s=argumentos.tempo_limite,
    )

    logging.info("mensagens processadas: %d", entregues)


if __name__ == "__main__":
    main()
