
from typing import Protocol

"fronteira de publicação com o barramento de eventos (B3)"
"o adaptador Kafka fica em kafka_adapter.py; aqui só o contrato interno"


class PublicadorAlertas(Protocol):
    """
    Contrato que um adaptador de barramento deve cumprir
    para publicar mensagens do S3: ods.s3.alert e as
    replies dos comandos.

    Recebe a mensagem já serializada. O tópico sai do
    campo schema (um tópico por schema).
    """

    def publicar(self, mensagem: str) -> None:
        ...
