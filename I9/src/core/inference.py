import random
from src.domain.models import RelacaoPessoaEPI, EstadoTrino

class RelationInferenceModule:
    """
    Núcleo de classificação (modelo neural/aprendido) que avalia o recorte e gera 
    os três estados e taxas de confiança.
    """
    def infer_states(self, relacao: RelacaoPessoaEPI) -> RelacaoPessoaEPI:
        """
        Simula a inferência. Na prática, este módulo chamaria o modelo em GPU (P2)
        recebendo o crop da imagem e as coordenadas.
        """
        for epi in relacao.epis:
            estados_possiveis = list(EstadoTrino)
            epi.estado_relacional = random.choice(estados_possiveis)
            epi.confianca_relacional = round(random.uniform(0.6, 0.99), 2)
            
        return relacao
