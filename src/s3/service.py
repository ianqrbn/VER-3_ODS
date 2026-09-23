
from uuid import uuid4

from s3.contracts import EventoQualificado
from s3.alert import Alerta
from s3.repository import AlertRepository
from s3.routing import RoteadorAlertas


"criação/orquestração"
"cria o alerta"

class AlertService:
    
    """Serviço responsável pela criaçãoe pelo processamento de alertas."""

    def __init__(
        self,
        repository: AlertRepository | None = None,
        roteador: RoteadorAlertas | None = None,
    ) -> None:

        self.repository = (
            repository
            if repository is not None
            else AlertRepository()
        )

        self.roteador = roteador

    def criar_alerta(
        self,
        evento: EventoQualificado,
        severidade: str,
        destinatarios: list[str],
        canais: list[str],
    ) -> Alerta:
        """
        Cria um alerta válido, mas não o armazena.
        """

        evento.validar()

        alerta = Alerta(
            alerta_id=str(uuid4()),
            evento_id=evento.evento_id,
            severidade=severidade,
            destinatarios=list(destinatarios),
            canais=list(canais),
            evidencia_ref=evento.evidencia_ref,
        )

        alerta.validar()

        return alerta

    def processar_evento(
        self,
        evento: EventoQualificado,
        severidade: str,
        destinatarios: list[str],
        canais: list[str],
    ) -> Alerta:
        """
        Processa um evento e evita duplicatas
        sequenciais no repositório em memória.
        """

        evento.validar()

        # Verifica se o evento já foi processado.
        alerta_existente = (
            self.repository.buscar_por_evento(
                evento.evento_id
            )
        )

        if alerta_existente is not None:
            return alerta_existente

        # Cria o alerta.
        alerta = self.criar_alerta(
            evento=evento,
            severidade=severidade,
            destinatarios=destinatarios,
            canais=canais,
        )

        # Salva o alerta e registra sua criação.
        self.repository.salvar(alerta)

        return alerta

    def processar_evento_roteado(
        self,
        evento: EventoQualificado,
    ) -> Alerta:
        """
        Processa um evento utilizando
        o roteador configurado.
        """

        evento.validar()

        if self.roteador is None:
            raise ValueError(
                "O serviço não possui um roteador configurado."
            )

        # Obtém severidade, destinatários e canais.
        configuracao = self.roteador.resolver(evento)

        # Reutiliza a lógica de processamento.
        return self.processar_evento(
            evento=evento,
            severidade=configuracao.severidade,
            destinatarios=list(configuracao.destinatarios),
            canais=list(configuracao.canais),
        )