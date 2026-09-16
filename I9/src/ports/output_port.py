from typing import Protocol
from src.domain.models import FrameContexto

class OutputPort(Protocol):
    """
    Protocolo que define como o módulo principal envia os eventos de conformidade (S2/A5).
    """
    def publish_event(self, frame_context: FrameContexto) -> None:
        """
        Publica o evento contendo os estados relacionais gerados pela inferência.
        """
        ...
