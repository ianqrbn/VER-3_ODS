
from s3.alert import Alerta
from s3.contracts import EventoQualificado
from s3.envelope import PERFIL_EV_SERVICO, decodificar, validar_envelope
from s3.service import AlertService

'adaptador de JSON'
'Recebe ods.s2.event do barramento e transforma em evento'

SCHEMA_ENTRADA = "ods.s2.event"


class IngestorEventos:
    """
    Recebe mensagens ods.s2.event e as encaminha ao S3.

    Mensagem inválida gera ErroS3 (ValueError): quem
    assina o barramento descarta e registra em log.
    """

    def __init__(self, service: AlertService) -> None:
        self.service = service

    def receber(self, mensagem: str | bytes) -> Alerta | None:
        """
        Valida a mensagem e processa o evento.

        Retorna o alerta do evento, ou None se o evento
        não gera alerta ou se a mensagem já foi processada.
        """

        # 1. Decodificar e validar o envelope.
        dados = decodificar(mensagem)

        validar_envelope(
            dados, SCHEMA_ENTRADA, "event", PERFIL_EV_SERVICO
        )

        # 2. Descartar a mesma mensagem recebida de novo.
        message_id = dados["message_id"]
        repository = self.service.repository

        if repository.mensagem_processada(message_id):
            return None

        # 3. Construir e validar o evento.
        evento = EventoQualificado.de_mensagem(dados)

        # 4. Encaminhar para o serviço.
        alerta = self.service.processar_evento_roteado(evento)

        # Só marca depois de processar: se falhar,
        # a mensagem pode ser entregue de novo.
        repository.registrar_mensagem(message_id)

        return alerta
