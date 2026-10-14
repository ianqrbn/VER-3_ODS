
from typing import Protocol

"fronteira de publicação com o barramento de eventos (B2)"
"o adaptador concreto ainda não existe; aqui só o contrato interno"


class PublicadorAlertas(Protocol):
    """
    Contrato que um adaptador de barramento real (B2) deve cumprir
    para entregar os alertas do S3 às aplicações.

    Recebe a mensagem já serializada (envelope de jsons/saida.json).
    Tecnologia, tópico e garantias de entrega são definidos pelo TRA-1.
    """

    def publicar(self, mensagem: str) -> None:
        ...
