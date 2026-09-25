
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

"modelo do registro auditável"
'Registra o histórico'


@dataclass(frozen=True)
class RegistroHistorico:
    """
    Representa uma ação registrada no histórico
    de um alerta.

    Modelo interno provisório do S3.
    """

    alerta_id: str
    evento_id: str
    acao: str

    autor_id: str | None = None

    registro_id: str = field(
        default_factory=lambda: str(uuid4())
    )

    registrado_em: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        """Valida o registro após sua criação."""

        if not self.alerta_id:
            raise ValueError(
                "O registro precisa de um alerta."
            )

        if not self.evento_id:
            raise ValueError(
                "O registro precisa de um evento."
            )

        acoes_permitidas = {
            "CRIADO",
            "RECONHECIDO",
            "SILENCIADO",
            "ENCERRADO"
        }

        if self.acao not in acoes_permitidas:
            raise ValueError(
                "Ação de histórico inválida."
            )

        if self.acao != "CRIADO" and not self.autor_id:
            raise ValueError(
                "A ação precisa identificar o responsável."
            )

        if (
            self.registrado_em.tzinfo is None
            or self.registrado_em.utcoffset() is None
        ):
            raise ValueError(
                "O horário precisa conter fuso horário."
            )