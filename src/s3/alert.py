
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

"modelo do alerta"

@dataclass
class Alerta:

    alerta_id: str
    evento_id: str
    severidade: str
    destinatarios: list[str]
    canais: list[str]

    evidencia_ref: Optional[str] = None

    estado: str = "CRIADO"

    criado_em: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def validar(self) -> None:

        if not self.alerta_id:
            raise ValueError("O alerta precisa de um ID.")

        if not self.evento_id:
            raise ValueError(
                "O alerta precisa de um evento de origem."
            )

        if not self.severidade:
            raise ValueError("A severidade é obrigatória.")

        if not self.destinatarios:
            raise ValueError(
                "O alerta precisa de destinatários."
            )

        if not self.canais:
            raise ValueError(
                "O alerta precisa de canais de entrega."
            )
            
if __name__ == "__main__":
    evento = Alerta(
        alerta_id="evt-001",
        evento_id="VIOLACAO_EPI",
        severidade="S2",
        destinatarios="[]",
        canais="[]"
    )

    evento.validar()

    print("Evento validado com sucesso!")
    print(evento)