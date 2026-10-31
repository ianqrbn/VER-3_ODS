from typing import Optional, Protocol

from src.domain.models import DetectionFrame


class IngestionPort(Protocol):
    """
    Protocolo de consumo dos eventos de detecção (I1 / `ods.i1.detections`).

    A implementação concreta é responsável por assinar o barramento pub/sub,
    validar o envelope e devolver o quadro já convertido para o domínio.
    """

    def get_next_event(self) -> Optional[DetectionFrame]:
        """Próximo quadro disponível, ou None quando não há (ou a fonte esgotou)."""
        ...
