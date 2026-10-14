from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from s3.envelope import agora
from s3.errors import (
    INVALID_CHANNEL,
    INVALID_PAYLOAD,
    INVALID_RECIPIENT,
    ErroS3,
)

"modelo do alerta"
'Valores dos enums conforme ods.s3.alert (Especificação 1.0, seção 7)'

ESTADOS = {"CREATED", "ACKNOWLEDGED", "MUTED", "CLOSED"}
SEVERIDADES = {"HIGH", "MEDIUM", "LOW"}
CANAIS = {"SOUND", "SCREEN", "PUSH"}
PREFIXOS_DESTINATARIO = ("user:", "group:", "role:")


def validar_destinatarios(destinatarios: object) -> None:
    """
    Lista de user:<id>, group:<id> ou role:<id>.

    Um texto solto é rejeitado: ("sup-01") sem vírgula
    não é uma tupla, e viraria uma lista de letras.
    """

    if (
        not isinstance(destinatarios, (list, tuple))
        or not destinatarios
    ):
        raise ErroS3(
            INVALID_RECIPIENT,
            "Os destinatários devem ser uma lista não vazia.",
        )

    for destinatario in destinatarios:
        if not isinstance(destinatario, str) or not any(
            destinatario.startswith(prefixo)
            and destinatario[len(prefixo):].strip()
            for prefixo in PREFIXOS_DESTINATARIO
        ):
            raise ErroS3(
                INVALID_RECIPIENT,
                f"Destinatário inválido: {destinatario!r}",
            )


def validar_canais(canais: object) -> None:
    """Lista não vazia de SOUND, SCREEN ou PUSH."""

    if not isinstance(canais, (list, tuple)) or not canais:
        raise ErroS3(
            INVALID_CHANNEL, "Os canais devem ser uma lista não vazia."
        )

    for canal in canais:
        if canal not in CANAIS:
            raise ErroS3(INVALID_CHANNEL, f"Canal inválido: {canal!r}")


def validar_severidade(severidade: object) -> None:

    if severidade not in SEVERIDADES:
        raise ErroS3(
            INVALID_PAYLOAD, f"Severidade inválida: {severidade!r}"
        )


def _texto(valor: object, campo: str) -> None:
    if not isinstance(valor, str) or not valor.strip():
        raise ErroS3(INVALID_PAYLOAD, f"{campo} deve ser um texto não vazio.")


@dataclass
class Alerta:
    """
    Modelo interno de um alerta do S3.
    """

    alerta_id: str                            # alert_id
    severidade: str                           # severity
    destinatarios: list[str]                  # recipients
    canais: list[str]                         # channels
    titulo: str                               # title
    mensagem: str                             # message

    evento_id: Optional[str] = None           # event_id
    clip_id: Optional[str] = None
    estado: str = "CREATED"                   # state

    criado_em: datetime = field(default_factory=agora)

    reconhecido_por: Optional[str] = None     # acknowledged_by
    reconhecido_em: Optional[datetime] = None
    silenciado_ate: Optional[datetime] = None  # muted_until
    encerrado_por: Optional[str] = None       # closed_by
    encerrado_em: Optional[datetime] = None

    # Contexto usado no envelope de ods.s3.alert.
    origem: Optional[str] = None              # source_id
    session_id: Optional[str] = None
    capturado_em: Optional[datetime] = None   # captured_at
    correlacao_id: Optional[str] = None       # correlation_id
    versao_roteamento: Optional[str] = None   # artifact_version

    def validar(self) -> None:

        _texto(self.alerta_id, "alert_id")
        _texto(self.titulo, "title")
        _texto(self.mensagem, "message")

        if self.evento_id is not None:
            _texto(self.evento_id, "event_id")

        validar_severidade(self.severidade)
        validar_destinatarios(self.destinatarios)
        validar_canais(self.canais)

        if self.estado not in ESTADOS:
            raise ErroS3(INVALID_PAYLOAD, f"Estado inválido: {self.estado}")

        for horario in (
            self.criado_em,
            self.reconhecido_em,
            self.silenciado_ate,
            self.encerrado_em,
            self.capturado_em,
        ):
            if horario is not None and (
                horario.tzinfo is None or horario.utcoffset() is None
            ):
                raise ErroS3(
                    INVALID_PAYLOAD,
                    "Os horários do alerta precisam de fuso.",
                )
