
from dataclasses import dataclass
from typing import Optional

"modelo do evento recebido"
"Valida o JSON recebido pelo ingestion.py como Evento Qualificado"

@dataclass
class EventoQualificado:

    evento_id: str
    tipo: str
    origem: str
    timestamp: str
    confianca: float

    pessoa_id: Optional[str] = None
    zona_id: Optional[str] = None
    evidencia_ref: Optional[str] = None

    def validar(self) -> None:

        if not self.evento_id:
            raise ValueError("O evento precisa de um ID.")

        if not self.tipo:
            raise ValueError("O evento precisa de um tipo.")

        if not self.origem:
            raise ValueError("O evento precisa de uma origem.")

        if not self.timestamp:
            raise ValueError("O evento precisa de um timestamp.")

        if not 0 <= self.confianca <= 1:
            raise ValueError(
                "A confiança deve estar entre 0 e 1."
            )

if __name__ == "__main__":
    evento = EventoQualificado(
        evento_id="evt-001",
        tipo="VIOLACAO_EPI",
        origem="S2",
        timestamp="2026-09-18T10:00:00Z",
        confianca=0.96
    )

    evento.validar()

    print("Evento validado com sucesso!")
    print(evento)