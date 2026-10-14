
import json
from datetime import datetime, timezone

from s3.alert import Alerta

"serialização da saída"
'Transforma o alerta no envelope de jsons/saida.json (não publica)'

SCHEMA_SAIDA = "ods.alertas.alerta"
VERSAO_SCHEMA_SAIDA = "1.0"
PRODUTOR = "S3"


def formatar_horario(horario: datetime) -> str:
    """
    Converte um horário com fuso para ISO 8601 em UTC,
    no formato dos exemplos: 2026-10-01T18:00:00Z.
    """

    if horario.tzinfo is None or horario.utcoffset() is None:
        raise ValueError(
            "O horário precisa conter fuso horário."
        )

    return (
        horario.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def serializar_alerta(
    alerta: Alerta,
    publicado_em: datetime | None = None,
) -> dict:
    """
    Monta o envelope de saída de um alerta.

    Envelope provisório conforme jsons/saida.json;
    o schema oficial ainda depende do B1.
    """

    alerta.validar()

    if publicado_em is None:
        publicado_em = datetime.now(timezone.utc)

    return {
        "message_type": "event",
        "schema": SCHEMA_SAIDA,
        "schema_version": VERSAO_SCHEMA_SAIDA,
        "producer": PRODUTOR,
        "published_at": formatar_horario(publicado_em),
        "payload": {
            "alerta_id": alerta.alerta_id,
            "evento_id": alerta.evento_id,
            "severidade": alerta.severidade,
            "destinatarios": list(alerta.destinatarios),
            "canais": list(alerta.canais),
            "evidencia_ref": alerta.evidencia_ref,
            "estado": alerta.estado,
            "criado_em": formatar_horario(alerta.criado_em),
        },
    }


def alerta_para_json(
    alerta: Alerta,
    publicado_em: datetime | None = None,
) -> str:
    """
    Serializa o envelope de saída como texto JSON.
    """

    return json.dumps(
        serializar_alerta(alerta, publicado_em),
        ensure_ascii=False,
    )
