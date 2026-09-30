from typing import Protocol

from src.domain.models import RelationalEvent


class OutputPort(Protocol):
    """
    Protocolo de publicação dos eventos relacionais (I9 / `ods.inferencia.relacional`),
    consumidos pelos módulos de conformidade (S2/A5).
    """

    def publish_event(self, event: RelationalEvent) -> None:
        """Publica o evento contendo os estados relacionais gerados pela inferência."""
        ...
