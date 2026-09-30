from typing import Optional, Protocol

from src.domain.models import TrackingFrame


class IngestionPort(Protocol):
    """
    Protocolo de consumo dos eventos de rastreio (I2 / `ods.inferencia.rastreio`).

    A implementação concreta é responsável por assinar o barramento pub/sub,
    validar o envelope e devolver o payload já convertido para o domínio.
    """

    def get_next_event(self) -> Optional[TrackingFrame]:
        """Próximo quadro disponível, ou None quando não há (ou a fonte esgotou)."""
        ...
