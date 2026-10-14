
import logging
from typing import Callable, Protocol

from s3.alert import Alerta
from s3.commands import ProcessadorComandos
from s3.envelope import decodificar
from s3.ingestion import SCHEMA_ENTRADA, IngestorEventos
from s3.publication import PublicadorAlertas

"fronteira de assinatura com o barramento de eventos (B3)"
"o adaptador Kafka fica em kafka_adapter.py; aqui só o contrato interno"

logger = logging.getLogger(__name__)


class AssinanteEventos(Protocol):
    """
    Contrato que um adaptador de barramento deve cumprir
    para entregar mensagens ao S3 (texto ou bytes).
    """

    def assinar(self, callback: Callable[[str | bytes], object]) -> None:
        ...


class ConectorEventos:
    """
    Liga um assinante de ods.s2.event ao ingestor do S3.

    Mensagem inválida é descartada e registrada em log,
    nunca processada "na tentativa" (Guia do Kafka, 4.3).
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
        Registra o conector como callback do assinante.
        """

        self.assinante.assinar(self.entregar)

    def entregar(self, mensagem: str | bytes) -> Alerta | None:
        try:
            return self.ingestor.receber(mensagem)
        except ValueError as erro:
            logger.warning("mensagem descartada: %s", erro)
            return None


class ConectorComandos:
    """
    Liga um assinante dos comandos do S3 ao processador
    e publica a reply de cada comando.
    """

    def __init__(
        self,
        assinante: AssinanteEventos,
        processador: ProcessadorComandos,
        publicador_respostas: PublicadorAlertas,
    ) -> None:

        self.assinante = assinante
        self.processador = processador
        self.publicador_respostas = publicador_respostas

    def conectar(self) -> None:
        self.assinante.assinar(self.entregar)

    def entregar(self, mensagem: str | bytes) -> str | None:
        try:
            resposta = self.processador.receber(mensagem)
        except ValueError as erro:
            logger.warning("comando descartado: %s", erro)
            return None

        self.publicador_respostas.publicar(resposta)

        return resposta


class DespachanteS3:
    """
    Um único assinante para todos os tópicos do S3:
    envia ods.s2.event ao ingestor e o resto aos comandos.
    """

    def __init__(
        self,
        eventos: ConectorEventos,
        comandos: ConectorComandos,
    ) -> None:

        self.eventos = eventos
        self.comandos = comandos

    def conectar(self, assinante: AssinanteEventos) -> None:
        assinante.assinar(self.entregar)

    def entregar(self, mensagem: str | bytes) -> object:
        try:
            schema = decodificar(mensagem).get("schema")
        except ValueError as erro:
            logger.warning("mensagem descartada: %s", erro)
            return None

        if schema == SCHEMA_ENTRADA:
            return self.eventos.entregar(mensagem)

        return self.comandos.entregar(mensagem)
