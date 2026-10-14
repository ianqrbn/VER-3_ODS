
import json
from datetime import datetime

from s3.alert import Alerta
from s3.envelope import formatar_horario, montar_envelope

"serialização da saída"
'Transforma o alerta em ods.s3.alert (Especificação 1.0, seção 7); não publica'

SCHEMA_ALERTA = "ods.s3.alert"


def payload_alerta(alerta: Alerta) -> dict:
    """
    Payload de ods.s3.alert. Campos opcionais sem
    valor são omitidos. Também é o item da reply
    de ods.s3.alerts.query.
    """

    alerta.validar()

    payload = {"alert_id": alerta.alerta_id}

    if alerta.evento_id is not None:
        payload["event_id"] = alerta.evento_id

    payload.update({
        "title": alerta.titulo,
        "message": alerta.mensagem,
        "severity": alerta.severidade,
        "recipients": list(alerta.destinatarios),
        "channels": list(alerta.canais),
    })

    if alerta.clip_id is not None:
        payload["clip_id"] = alerta.clip_id

    payload["state"] = alerta.estado
    payload["created_at"] = formatar_horario(alerta.criado_em)

    for campo, valor in (
        ("acknowledged_by", alerta.reconhecido_por),
        ("acknowledged_at", alerta.reconhecido_em),
        ("muted_until", alerta.silenciado_ate),
        ("closed_by", alerta.encerrado_por),
        ("closed_at", alerta.encerrado_em),
    ):
        if valor is None:
            continue

        payload[campo] = (
            formatar_horario(valor)
            if isinstance(valor, datetime)
            else valor
        )

    return payload


def serializar_alerta(
    alerta: Alerta,
    sequence: int = 0,
    publicado_em: datetime | None = None,
    message_id: str | None = None,
) -> dict:
    """
    Monta a mensagem ods.s3.alert (perfil EV-SERVIÇO).

    captured_at: o do evento de origem; em alerta criado
    por comando, o horário de criação.
    """

    return montar_envelope(
        "event",
        SCHEMA_ALERTA,
        payload_alerta(alerta),
        publicado_em=publicado_em,
        message_id=message_id,
        correlation_id=alerta.correlacao_id,
        captured_at=alerta.capturado_em or alerta.criado_em,
        source_id=alerta.origem,
        session_id=alerta.session_id,
        sequence=sequence,
        artifact_version=alerta.versao_roteamento,
    )


def alerta_para_json(alerta: Alerta, **opcoes: object) -> str:
    """
    Serializa ods.s3.alert como texto JSON.
    """

    return json.dumps(
        serializar_alerta(alerta, **opcoes),
        ensure_ascii=False,
    )
