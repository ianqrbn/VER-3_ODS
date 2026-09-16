from typing import List
from src.domain.models import Pessoa, EPI, RelacaoPessoaEPI

class PairingModule:
    """
    Responsável por associar bounding boxes de EPIs às pessoas,
    utilizando heurísticas de proximidade espacial ou interseção (IoU).
    """
    def __init__(self, proximity_threshold: float = 0.5):
        self.proximity_threshold = proximity_threshold

    def pair_entities(self, pessoas: List[Pessoa], epis: List[EPI]) -> List[RelacaoPessoaEPI]:
        # Implementação "mock" simples:
        # Aqui vamos apenas atribuir todos os EPIs à primeira pessoa encontrada por simplicidade
        relacoes = []
        
        if not pessoas:
            return relacoes
            
        # Atribui tudo à primeira pessoa (Simulação)
        relacao = RelacaoPessoaEPI(pessoa=pessoas[0], epis=epis)
        relacoes.append(relacao)
        
        return relacoes
