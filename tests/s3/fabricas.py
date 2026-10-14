"""
Dados de apoio dos testes: mensagens e objetos válidos
segundo a Especificação de interfaces 1.0.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from s3.contracts import EventoQualificado
from s3.routing import ConfiguracaoRoteamento, RoteadorAlertas

PASTA_JSONS = Path(__file__).resolve().parents[2] / "jsons"

FUTURO = datetime(2030, 1, 1, tzinfo=timezone.utc)


def ler_json(nome: str) -> dict:
    with open(PASTA_JSONS / nome, encoding="utf-8") as arquivo:
        return json.load(arquivo)


def texto_json(nome: str) -> str:
    with open(PASTA_JSONS / nome, encoding="utf-8") as arquivo:
        return arquivo.read()


def evento(**alteracoes) -> EventoQualificado:
    dados = dict(
        evento_id="evt-001",
        tipo="PPE_NON_COMPLIANT",
        iniciado_em="2026-09-23T14:29:52.000Z",
        confianca=0.81,
        regra_id="a5-luva-galpao",
        entidade_id="e-7a21",
        classe="person",
        zona_id="galpao-solda",
        equipamento="luva",
        duracao_ms=8000,
        source_ids=["cam0"],
        origem="cam0",
        session_id="sessao-1",
        capturado_em="2026-09-23T14:29:59.870Z",
    )
    dados.update(alteracoes)
    return EventoQualificado(**dados)


def rota(**alteracoes) -> ConfiguracaoRoteamento:
    dados = dict(
        severidade="HIGH",
        destinatarios=("role:supervisor",),
        canais=("SCREEN", "PUSH"),
        titulo="EPI ausente: {equipment_item}",
        mensagem="Pessoa sem {equipment_item} em {zone_id} há {duration_s} s",
    )
    dados.update(alteracoes)
    return ConfiguracaoRoteamento(**dados)


def roteador(**alteracoes) -> RoteadorAlertas:
    return RoteadorAlertas(
        {"PPE_NON_COMPLIANT": rota(**alteracoes)},
        versao="routing-a5-1",
    )


def mensagem_evento(payload: dict | None = None, **envelope) -> dict:
    """ods.s2.event completo; payload e envelope sobrescrevem campos."""

    dados = ler_json("entrada.json")
    dados["message_id"] = str(uuid4())
    dados["payload"].update(payload or {})
    dados.update(envelope)
    return dados


def comando(schema: str, payload: dict, **envelope) -> dict:
    """Comando ou consulta para o S3, com message_id novo."""

    dados = {
        "message_type": "query" if schema.endswith(".query") else "command",
        "message_id": str(uuid4()),
        "schema": schema,
        "schema_version": "1.0",
        "producer": "A5",
        "published_at": "2026-09-23T14:30:41.000Z",
        "target": "S3",
        "payload": payload,
    }
    dados.update(envelope)
    return dados


def mais(horario: datetime, segundos: float) -> datetime:
    return horario + timedelta(seconds=segundos)


class PublicadorFalso:
    """Substituto do adaptador real do B3: só guarda as mensagens."""

    def __init__(self):
        self.mensagens = []

    def publicar(self, mensagem):
        self.mensagens.append(json.loads(mensagem))


class AssinanteFalso:
    """Substituto do assinante real: guarda o callback."""

    def __init__(self):
        self.callback = None

    def assinar(self, callback):
        self.callback = callback

    def publicar(self, mensagem):
        if self.callback is None:
            raise RuntimeError("Nenhum callback registrado.")
        return self.callback(mensagem)
