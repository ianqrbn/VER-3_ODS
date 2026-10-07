
from typing import Callable, Protocol

from s3.alert import Alerta
from s3.ingestion import IngestorEventos

"fronteira de assinatura com o barramento de eventos (B2)"
"o adaptador concreto ainda não existe; aqui só o contrato interno"


class AssinanteEventos(Protocol):
    """
    Contrato que um adaptador de barramento real (B2) deve cumprir
    para entregar mensagens ao S3.

    Nenhuma implementação concreta foi escolhida ainda: tecnologia,
    tópico, ack/retry e ordenação são definidos pelo TRA-1.
    """

    def assinar(self, callback: Callable[[str], Alerta]) -> None:
        ...


class ConectorEventos:
    """
    Liga um assinante de eventos ao ingestor do S3.

    Não escolhe nem instancia o transporte concreto: isso é
    responsabilidade do adaptador fornecido como `assinante`.
    """

    def __init__(
        self,
        assinante: AssinanteEventos,
        ingestor: IngestorEventos,
    ) -> None:

        self.assinante = assinante
        self.ingestor = ingestor

    def conectar(self) -> None:
        """
        Registra o ingestor como callback do assinante.
        """

        self.assinante.assinar(self.ingestor.receber)
