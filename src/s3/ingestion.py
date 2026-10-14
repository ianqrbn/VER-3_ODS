
import json

from s3.alert import Alerta
from s3.contracts import EventoQualificado
from s3.service import AlertService

'adaptador de JSON'
'Recebe o JSON do B3 e transforma em dados'

SCHEMA_ENTRADA = "ods.eventos.qualificados"

class IngestorEventos:
    """
    Recebe mensagens JSON e as encaminha ao S3.

    Adaptador provisório de entrada.
    A integração com B3 será adicionada depois.
    """

    def __init__(self, service: AlertService) -> None:
        self.service = service

    def receber(self, mensagem: str) -> Alerta:
        """
        Converte uma mensagem JSON em evento qualificado
        e solicita seu processamento.
        """

        # 1. Decodificar a mensagem.
        try:
            dados = json.loads(mensagem)
        except (json.JSONDecodeError, TypeError) as erro:
            raise ValueError(
                "Mensagem JSON inválida."
            ) from erro

        # 2. Verificar a estrutura básica.
        if not isinstance(dados, dict):
            raise ValueError(
                "A mensagem deve conter um objeto JSON."
            )

        # 3. Extrair o payload, se a mensagem vier no envelope
        #    documentado em jsons/entrada.json.
        if "payload" in dados:
            dados = self._abrir_envelope(dados)

        # 4. Construir o evento.
        try:
            evento = EventoQualificado(**dados)
        except TypeError as erro:
            raise ValueError(
                "Estrutura do evento inválida."
            ) from erro

        # 5. Validar o evento.
        evento.validar()

        # 6. Encaminhar para o serviço.
        return self.service.processar_evento_roteado(
            evento
        )

    @staticmethod
    def _abrir_envelope(dados: dict) -> dict:
        """
        Valida o envelope provisório e retorna o payload.

        Envelope conforme jsons/entrada.json; o schema
        oficial ainda depende do B1.
        """

        if dados.get("message_type") != "event":
            raise ValueError(
                "Tipo de mensagem inválido."
            )

        if dados.get("schema") != SCHEMA_ENTRADA:
            raise ValueError(
                "Schema da mensagem inválido."
            )

        for campo in ("schema_version", "producer"):
            valor = dados.get(campo)

            if not isinstance(valor, str) or not valor.strip():
                raise ValueError(
                    f"O envelope precisa de {campo}."
                )

        payload = dados["payload"]

        if not isinstance(payload, dict):
            raise ValueError(
                "O payload deve ser um objeto JSON."
            )

        return payload