from typing import Protocol

from src.domain.models import ComplianceEvent


class OutputPort(Protocol):
    """
    Protocolo de publicação da conformidade de EPI (I9 / `ods.i9.ppe_compliance`),
    consumida por S2 e A5.
    """

    def publish_event(self, event: ComplianceEvent) -> None:
        """Publica o evento contendo os estados relacionais gerados pela inferência."""
        ...
