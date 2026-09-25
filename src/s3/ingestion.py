
import json

from s3.alert import Alerta
from s3.contracts import EventoQualificado
from s3.service import AlertService

'adaptador de JSON'
'Recebe o JSON do B3 e transforma em dados'

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

        # 3. Construir o evento.
        try:
            evento = EventoQualificado(**dados)
        except TypeError as erro:
            raise ValueError(
                "Estrutura do evento inválida."
            ) from erro

        # 4. Validar o evento.
        evento.validar()

        # 5. Encaminhar para o serviço.
        return self.service.processar_evento_roteado(
            evento
        )