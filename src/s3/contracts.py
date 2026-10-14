
from dataclasses import dataclass, field
from typing import Optional

from s3.envelope import ler_horario
from s3.errors import INVALID_PAYLOAD, ErroS3

"modelo do evento recebido"
'Evento qualificado de S2 (ods.s2.event, Especificação 1.0, seção 7)'

STATUS_EVENTO = {"CONFIRMED", "UNCERTAIN"}
FASES_EVENTO = {"STARTED", "UPDATED", "ENDED"}

# Campos obrigatórios do payload de ods.s2.event.
CAMPOS_OBRIGATORIOS = (
    "event_id",
    "event_type",
    "rule_id",
    "status",
    "phase",
    "confidence",
    "started_at",
    "duration_ms",
    "source_ids",
)


def _texto(valor: object, campo: str) -> None:
    if not isinstance(valor, str) or not valor.strip():
        raise ErroS3(INVALID_PAYLOAD, f"{campo} deve ser um texto não vazio.")


def _texto_opcional(valor: object, campo: str) -> None:
    if valor is not None:
        _texto(valor, campo)


@dataclass
class EventoQualificado:
    """
    Evento qualificado recebido do S2.

    Os nomes são internos; a tradução para os campos
    do contrato fica em de_mensagem().
    """

    evento_id: str                       # event_id
    tipo: str                            # event_type
    iniciado_em: str                     # started_at (ISO 8601)
    confianca: float                     # confidence

    status: str = "CONFIRMED"            # status
    fase: str = "STARTED"                # phase
    regra_id: Optional[str] = None       # rule_id
    entidade_id: Optional[str] = None    # entity_id
    classe: Optional[str] = None         # class
    zona_id: Optional[str] = None        # zone_id
    equipamento: Optional[str] = None    # equipment_item
    duracao_ms: Optional[int] = None     # duration_ms
    source_ids: list[str] = field(default_factory=list)
    detalhes: dict = field(default_factory=dict)

    # Contexto do envelope.
    origem: Optional[str] = None         # source_id
    session_id: Optional[str] = None
    capturado_em: Optional[str] = None   # captured_at

    def validar(self) -> None:

        _texto(self.evento_id, "event_id")
        _texto(self.tipo, "event_type")
        ler_horario(self.iniciado_em, "started_at")

        if (
            isinstance(self.confianca, bool)
            or not isinstance(self.confianca, (int, float))
        ):
            raise ErroS3(INVALID_PAYLOAD, "A confiança deve ser numérica.")

        if not 0 <= self.confianca <= 1:
            raise ErroS3(
                INVALID_PAYLOAD, "A confiança deve estar entre 0 e 1."
            )

        if self.status not in STATUS_EVENTO:
            raise ErroS3(INVALID_PAYLOAD, f"status inválido: {self.status}")

        if self.fase not in FASES_EVENTO:
            raise ErroS3(INVALID_PAYLOAD, f"phase inválida: {self.fase}")

        for valor, campo in (
            (self.regra_id, "rule_id"),
            (self.entidade_id, "entity_id"),
            (self.classe, "class"),
            (self.zona_id, "zone_id"),
            (self.equipamento, "equipment_item"),
            (self.origem, "source_id"),
            (self.session_id, "session_id"),
        ):
            _texto_opcional(valor, campo)

        if self.duracao_ms is not None and (
            isinstance(self.duracao_ms, bool)
            or not isinstance(self.duracao_ms, int)
            or self.duracao_ms < 0
        ):
            raise ErroS3(INVALID_PAYLOAD, "duration_ms inválido.")

        if not isinstance(self.source_ids, list) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.source_ids
        ):
            raise ErroS3(INVALID_PAYLOAD, "source_ids inválido.")

        if not isinstance(self.detalhes, dict):
            raise ErroS3(INVALID_PAYLOAD, "details deve ser um objeto.")

        if self.capturado_em is not None:
            ler_horario(self.capturado_em, "captured_at")

    @classmethod
    def de_mensagem(cls, envelope: dict) -> "EventoQualificado":
        """
        Cria o evento a partir de uma mensagem ods.s2.event
        cujo envelope já foi validado.
        """

        payload = envelope["payload"]

        for campo in CAMPOS_OBRIGATORIOS:
            if payload.get(campo) is None:
                raise ErroS3(
                    INVALID_PAYLOAD, f"Campo obrigatório ausente: {campo}"
                )

        evento = cls(
            evento_id=payload["event_id"],
            tipo=payload["event_type"],
            iniciado_em=payload["started_at"],
            confianca=payload["confidence"],
            status=payload["status"],
            fase=payload["phase"],
            regra_id=payload["rule_id"],
            entidade_id=payload.get("entity_id"),
            classe=payload.get("class"),
            zona_id=payload.get("zone_id"),
            equipamento=payload.get("equipment_item"),
            duracao_ms=payload["duration_ms"],
            source_ids=payload["source_ids"],
            detalhes=payload.get("details") or {},
            origem=envelope.get("source_id"),
            session_id=envelope.get("session_id"),
            capturado_em=envelope.get("captured_at"),
        )

        evento.validar()

        return evento
