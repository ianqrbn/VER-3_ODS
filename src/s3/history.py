
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from s3.envelope import agora

"modelo do registro auditável"
'Registra o histórico'

ACOES = {"CREATED", "ACKNOWLEDGED", "MUTED", "CLOSED"}


@dataclass(frozen=True)
class RegistroHistorico:
    """
    Representa uma ação registrada no histórico
    de um alerta. A ação é o estado resultante.
    """

    alerta_id: str
    acao: str

    autor_id: str | None = None
    evento_id: str | None = None
    motivo: str | None = None              # reason
    silenciado_ate: datetime | None = None  # muted_until

    registro_id: str = field(
        default_factory=lambda: str(uuid4())
    )

    registrado_em: datetime = field(default_factory=agora)

    def __post_init__(self) -> None:
        """Valida o registro após sua criação."""

        if not self.alerta_id:
            raise ValueError(
                "O registro precisa de um alerta."
            )

        if self.acao not in ACOES:
            raise ValueError(
                "Ação de histórico inválida."
            )

        if self.acao != "CREATED" and (
            not isinstance(self.autor_id, str)
            or not self.autor_id.strip()
        ):
            raise ValueError(
                "A ação precisa identificar o responsável."
            )

        if self.acao == "MUTED" and self.silenciado_ate is None:
            raise ValueError(
                "O silenciamento precisa de mute_until."
            )

        for horario in (self.registrado_em, self.silenciado_ate):
            if horario is not None and (
                horario.tzinfo is None
                or horario.utcoffset() is None
            ):
                raise ValueError(
                    "O horário precisa conter fuso horário."
                )
