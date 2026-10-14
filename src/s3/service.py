
from uuid import uuid4

from s3.contracts import EventoQualificado
from s3.alert import Alerta
from s3.history import RegistroHistorico
from s3.output import alerta_para_json
from s3.publication import PublicadorAlertas
from s3.repository import AlertRepository
from s3.routing import RoteadorAlertas


"criação/orquestração"
"cria o alerta"

# Estado de destino → estados de origem permitidos.
TRANSICOES = {
    "RECONHECIDO": {"CRIADO"},
    "SILENCIADO": {"CRIADO", "RECONHECIDO"},
    "ENCERRADO": {"CRIADO", "RECONHECIDO", "SILENCIADO"},
}

class AlertService:
    
    """Serviço responsável pela criaçãoe pelo processamento de alertas."""

    def __init__(
        self,
        repository: AlertRepository | None = None,
        roteador: RoteadorAlertas | None = None,
        publicador: PublicadorAlertas | None = None,
    ) -> None:

        self.repository = (
            repository
            if repository is not None
            else AlertRepository()
        )

        self.roteador = roteador

        # Opcional: sem publicador, nada é enviado às aplicações.
        self.publicador = publicador

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

        # Evento repetido: não cria nem publica de novo.
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

        self._publicar(alerta)

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

    def reconhecer_alerta(
        self,
        alerta_id: str,
        autor_id: str,
    ) -> Alerta:
        """
        Registra que um responsável confirmou ter visto o alerta.
        """

        return self._mudar_estado(alerta_id, autor_id, "RECONHECIDO")

    def silenciar_alerta(
        self,
        alerta_id: str,
        autor_id: str,
    ) -> Alerta:
        """
        Silencia o alerta, registrando o responsável pela ação.
        """

        return self._mudar_estado(alerta_id, autor_id, "SILENCIADO")

    def encerrar_alerta(
        self,
        alerta_id: str,
        autor_id: str,
    ) -> Alerta:
        """
        Encerra o alerta. ENCERRADO é um estado final.
        """

        return self._mudar_estado(alerta_id, autor_id, "ENCERRADO")

    def _mudar_estado(
        self,
        alerta_id: str,
        autor_id: str,
        novo_estado: str,
    ) -> Alerta:
        """
        Aplica uma transição permitida e registra no histórico.

        Comandos repetidos ou fora de ordem são rejeitados,
        para não duplicar registros no histórico.
        """

        alerta = self.repository.buscar_por_id(alerta_id)

        if alerta is None:
            raise ValueError(
                "Alerta não encontrado."
            )

        if alerta.estado not in TRANSICOES[novo_estado]:
            raise ValueError(
                f"Transição inválida: {alerta.estado} → {novo_estado}."
            )

        # Registra antes de mudar o estado: se o histórico
        # falhar, o alerta permanece inalterado.
        registro = RegistroHistorico(
            alerta_id=alerta.alerta_id,
            evento_id=alerta.evento_id,
            acao=novo_estado,
            autor_id=autor_id,
        )

        self.repository.registrar_historico(registro)

        alerta.estado = novo_estado

        self._publicar(alerta)

        return alerta

    def _publicar(self, alerta: Alerta) -> None:
        """
        Envia o estado atual do alerta às aplicações,
        no envelope de jsons/saida.json.
        """

        if self.publicador is None:
            return

        self.publicador.publicar(alerta_para_json(alerta))