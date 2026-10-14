
import json
import logging
import os
import time
from typing import Callable

"adaptador Kafka (B3, TRA-1)"
'Implementa AssinanteEventos e PublicadorAlertas com confluent-kafka'

logger = logging.getLogger(__name__)

# O endereço é temporário (nuvem de testes): nunca fixo no código.
VARIAVEL_BROKER = "S3_KAFKA_BOOTSTRAP"
VARIAVEL_GRUPO = "S3_KAFKA_GROUP_ID"
GRUPO_PADRAO = "S3-alertas"

# Um tópico por schema (Especificação 1.0). O Guia do Kafka
# sugere outra nomenclatura (ods.alerta.emitido...): pendente
# com o TRA-1. Para trocar, passe o mapa schema → tópico.
TOPICOS_ENTRADA = (
    "ods.s2.event",
    "ods.s3.alert.command",
    "ods.s3.alert_action.command",
    "ods.s3.alerts.query",
)


def endereco_broker(endereco: str | None = None) -> str:
    """Endereço explícito ou da variável de ambiente."""

    endereco = endereco or os.environ.get(VARIAVEL_BROKER)

    if not endereco:
        raise RuntimeError(
            f"Defina {VARIAVEL_BROKER} com o endereço do broker (host:porta)."
        )

    return endereco


class AssinanteKafka:
    """
    Consome os tópicos do S3 e entrega cada mensagem
    ao callback registrado.

    O commit é manual e só acontece depois do callback:
    se o processo cair no meio, a mensagem é entregue
    de novo e a deduplicação do S3 cuida da repetição.
    """

    def __init__(
        self,
        topicos: tuple[str, ...] | list[str] = TOPICOS_ENTRADA,
        endereco: str | None = None,
        group_id: str | None = None,
        consumidor: object | None = None,
    ) -> None:

        self.topicos = list(topicos)
        self._endereco = endereco
        self._group_id = (
            group_id or os.environ.get(VARIAVEL_GRUPO) or GRUPO_PADRAO
        )

        # Injetável nos testes; criado sob demanda na execução.
        self._consumidor = consumidor
        self._callback: Callable[[bytes], object] | None = None
        self._parar = False

    def assinar(self, callback: Callable[[bytes], object]) -> None:
        self._callback = callback

    def parar(self) -> None:
        self._parar = True

    def _criar_consumidor(self) -> object:
        from confluent_kafka import Consumer

        return Consumer({
            "bootstrap.servers": endereco_broker(self._endereco),
            "group.id": self._group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        })

    def executar(
        self,
        max_mensagens: int | None = None,
        tempo_limite_s: float | None = None,
        intervalo_poll_s: float = 1.0,
    ) -> int:
        """
        Laço de consumo com condição de parada: número de
        mensagens, tempo limite ou parar(). O broker de
        testes é pago e compartilhado (Guia do Kafka, 4.5).

        Retorna quantas mensagens foram entregues.
        """

        if self._callback is None:
            raise RuntimeError("Chame assinar() antes de executar().")

        consumidor = self._consumidor or self._criar_consumidor()
        consumidor.subscribe(self.topicos)

        prazo = (
            time.monotonic() + tempo_limite_s
            if tempo_limite_s is not None
            else None
        )

        entregues = 0
        self._parar = False

        try:
            while not self._parar:
                if max_mensagens is not None and entregues >= max_mensagens:
                    break

                if prazo is not None and time.monotonic() >= prazo:
                    break

                mensagem = consumidor.poll(intervalo_poll_s)

                if mensagem is None:
                    continue

                if mensagem.error():
                    logger.warning("erro de leitura: %s", mensagem.error())
                    continue

                try:
                    self._callback(mensagem.value())
                except Exception:
                    # Sem commit: a mensagem volta na próxima leitura.
                    logger.exception("falha ao processar mensagem")
                    continue

                consumidor.commit(message=mensagem, asynchronous=False)
                entregues += 1
        finally:
            consumidor.close()

        return entregues


class PublicadorKafka:
    """
    Publica mensagens do S3 no tópico do seu schema.
    """

    def __init__(
        self,
        endereco: str | None = None,
        topicos: dict[str, str] | None = None,
        produtor: object | None = None,
        tempo_entrega_s: float = 10.0,
    ) -> None:

        self._endereco = endereco
        self._topicos = dict(topicos or {})
        self._produtor = produtor
        self._tempo_entrega_s = tempo_entrega_s

    def _obter_produtor(self) -> object:
        if self._produtor is None:
            from confluent_kafka import Producer

            self._produtor = Producer({
                "bootstrap.servers": endereco_broker(self._endereco),
            })

        return self._produtor

    def topico(self, schema: str) -> str:
        return self._topicos.get(schema, schema)

    def publicar(self, mensagem: str) -> None:
        """
        Publica e espera a entrega ao broker; se não for
        entregue no prazo, lança ConnectionError.
        """

        schema = json.loads(mensagem)["schema"]
        produtor = self._obter_produtor()

        produtor.produce(
            topic=self.topico(schema),
            value=mensagem.encode("utf-8"),
        )

        pendentes = produtor.flush(self._tempo_entrega_s)

        if pendentes:
            raise ConnectionError(
                f"Mensagem não entregue ao broker ({schema})."
            )
