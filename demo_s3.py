"""
Demonstração do componente S3 (Alertas e Notificações)
com os contratos da Especificação de interfaces 1.0.

Usa um assinante e um publicador falsos no lugar do Kafka:
não acessa o broker real.

Para rodar:
    PowerShell:  $env:PYTHONPATH = "src"; python demo_s3.py
    Git Bash:    PYTHONPATH=src python demo_s3.py
"""

import json
import logging
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from s3.commands import ProcessadorComandos
from s3.envelope import agora, formatar_horario
from s3.ingestion import IngestorEventos
from s3.routing import RoteadorAlertas
from s3.service import AlertService
from s3.subscription import ConectorComandos, ConectorEventos, DespachanteS3

PASTA_JSONS = Path(__file__).resolve().parent / "jsons"


class AssinanteDemo:
    """Substituto do assinante Kafka, só para esta demonstração."""

    def __init__(self):
        self.callback = None

    def assinar(self, callback):
        self.callback = callback

    def publicar(self, mensagem):
        return self.callback(mensagem)


class PublicadorDemo:
    """Substituto do publicador Kafka: imprime o que sairia."""

    def publicar(self, mensagem):
        dados = json.loads(mensagem)
        print(f"   [saída: {dados['schema']}]")
        print("   " + json.dumps(dados["payload"], ensure_ascii=False))


def ler(nome):
    return json.loads((PASTA_JSONS / nome).read_text(encoding="utf-8"))


def titulo(texto):
    print()
    print("=" * 60)
    print(texto)
    print("=" * 60)


def acao(alerta_id, action, **campos):
    payload = {"alert_id": alerta_id, "action": action, "actor": "user:maria"}
    payload.update(campos)
    return {
        "message_type": "command",
        "message_id": str(uuid4()),
        "schema": "ods.s3.alert_action.command",
        "schema_version": "1.0",
        "producer": "A5",
        "published_at": "2026-09-23T14:30:41.000Z",
        "target": "S3",
        "payload": payload,
    }


def main():
    # Acentos no console do Windows; log na mesma saída, em ordem.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    logging.basicConfig(
        level=logging.WARNING,
        format="   [log] %(message)s",
        stream=sys.stdout,
    )

    titulo("1. Montagem do S3 com o artefato ROUTING de A5")

    roteador = RoteadorAlertas.de_artefato(ler("routing_a5.json"), "routing-a5-1")
    publicador = PublicadorDemo()
    service = AlertService(roteador=roteador, publicador=publicador)

    assinante = AssinanteDemo()
    DespachanteS3(
        ConectorEventos(assinante, IngestorEventos(service)),
        ConectorComandos(assinante, ProcessadorComandos(service), publicador),
    ).conectar(assinante)

    print("Rota: PPE_NON_COMPLIANT → HIGH, role:supervisor, SCREEN + PUSH")

    titulo("2. S2 publica ods.s2.event (jsons/entrada.json)")

    entrada = (PASTA_JSONS / "entrada.json").read_text(encoding="utf-8")
    alerta = assinante.publicar(entrada)
    alerta_id = alerta.alerta_id

    titulo("3. A mesma mensagem chega de novo (entrega repetida)")

    print(f"Resultado: {assinante.publicar(entrada)} (descartada pelo message_id)")

    titulo("4. Supervisora reconhece o alerta (alert_action ACKNOWLEDGE)")

    comando = acao(alerta_id, "ACKNOWLEDGE")
    assinante.publicar(json.dumps(comando))

    titulo("5. O mesmo comando é reenviado: mesma reply, sem efeito novo")

    assinante.publicar(json.dumps(comando))

    titulo("6. Silencia por 30 minutos (MUTE) e depois encerra (CLOSE)")

    assinante.publicar(json.dumps(
        acao(alerta_id, "MUTE",
             mute_until=formatar_horario(agora() + timedelta(minutes=30)),
             reason="troca de turno")
    ))
    assinante.publicar(json.dumps(acao(alerta_id, "CLOSE")))

    titulo("7. Comando inválido: reconhecer um alerta encerrado")

    assinante.publicar(json.dumps(acao(alerta_id, "ACKNOWLEDGE")))

    titulo("8. Histórico de auditoria do alerta")

    for registro in service.repository.buscar_historico(alerta_id):
        print(
            f"   {registro.acao:<13} autor={registro.autor_id!s:<11} "
            f"motivo={registro.motivo!s:<15} em={registro.registrado_em}"
        )

    titulo("9. A2 cria um alerta de negócio (ods.s3.alert.command)")

    assinante.publicar(json.dumps(ler("comando_criar.json")))

    titulo("10. Consulta de histórico (ods.s3.alerts.query)")

    consulta = ler("consulta_alertas.json")
    consulta["payload"] = {"state": "CLOSED"}
    assinante.publicar(json.dumps(consulta))

    titulo("11. Mensagem inválida é descartada e registrada em log")

    assinante.publicar('{"schema": "ods.s2.event"}')

    titulo("Fim da demonstração")


if __name__ == "__main__":
    main()
