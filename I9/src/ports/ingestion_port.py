from typing import Protocol, Optional
from src.domain.models import FrameContexto

class IngestionPort(Protocol):
    """
    Protocolo que define como o módulo principal irá consumir dados da frente (I1).
    """
    def get_next_frame(self) -> Optional[FrameContexto]:
        """
        Retorna o próximo frame processado com as detecções (já convertidas para o domínio),
        ou None se não houver ou a fonte esgotar.
        """
        ...
