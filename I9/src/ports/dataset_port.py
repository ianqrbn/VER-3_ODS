from typing import List, Protocol

from src.domain.models import AnnotatedFrame


class DatasetPort(Protocol):
    """
    Protocolo de carregamento de dataset anotado para calibração.

    A implementação concreta lê o arquivo (CSV, JSON, etc.) e devolve uma lista
    de frames anotados com ground truth.
    """

    def load(self, path: str) -> List[AnnotatedFrame]:
        """Carrega o dataset e retorna os frames anotados."""
        ...
