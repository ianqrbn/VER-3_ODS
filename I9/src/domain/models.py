from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

class EstadoTrino(Enum):
    CORRETO = "CORRETO"
    INCORRETO = "INCORRETO"
    AUSENTE = "AUSENTE"

@dataclass
class BoundingBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float

@dataclass
class DeteccaoInterna:
    id_rastreio: str
    classe: str
    confianca: float
    bbox: BoundingBox

@dataclass
class Pessoa(DeteccaoInterna):
    pass

@dataclass
class EPI(DeteccaoInterna):
    estado_relacional: Optional[EstadoTrino] = None
    confianca_relacional: Optional[float] = None

@dataclass
class RelacaoPessoaEPI:
    pessoa: Pessoa
    epis: List[EPI]

@dataclass
class FrameContexto:
    frame_id: str
    timestamp: float
    pessoas_e_epis: List[RelacaoPessoaEPI]
