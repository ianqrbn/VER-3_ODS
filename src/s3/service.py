
import logging
from datetime import datetime
from uuid import uuid4

from s3.alert import Alerta
from s3.contracts import EventoQualificado
from s3.envelope import Sequencia, ler_horario
from s3.errors import ALERT_NOT_FOUND, INVALID_TRANSITION, ErroS3
from s3.history import RegistroHistorico
from s3.output import alerta_para_json
from s3.publication import PublicadorAlertas
from s3.repository import AlertRepository
from s3.routing import (
    ConfiguracaoRoteamento,
    RoteadorAlertas,
    renderizar,
)


"criação/orquestração"
"cria o alerta"

logger = logging.getLogger(__name__)

# Estado de destino → estados de origem permitidos.
# A especificação define os estados, não as transições:
# esta tabela é decisão do VER-3 (pendente de revisão).
TRANSICOES = {
    "ACKNOWLEDGED": {"CREATED"},
    "MUTED": {"CREATED", "ACKNOWLEDGED"},
    "CLOSED": {"CREATED", "ACKNOWLEDGED", "MUTED"},
}


class AlertService:

    """Serviço responsável pela criação e pelo ciclo de vida dos alertas."""

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

        self._sequencia = Sequencia()

    def processar_evento(
        self,
        evento: EventoQualificado,
        rota: ConfiguracaoRoteamento,
    ) -> Alerta | None:
        """
        Cria o alerta de um evento, um por event_id.

        Com alerta existente, qualquer fase devolve o alerta
        sem alterá-lo. Sem alerta existente, STARTED e UPDATED
        criam (UPDATED: o STARTED se perdeu, a violação segue);
        ENDED não cria, porque a violação já terminou.

        O fim da violação (ENDED) não encerra o alerta: o
        encerramento é ação humana (CLOSE). Pendente com o A5.
        """

        evento.validar()

        # Evento repetido: não cria nem publica de novo.
        alerta_existente = self.repository.buscar_por_evento(
            evento.evento_id
        )

        if alerta_existente is not None:
            return alerta_existente

        if evento.fase == "ENDED":
            logger.warning(
                "ENDED sem alerta existente; nenhum alerta criado: %s",
                evento.evento_id,
            )
            return None

        alerta = Alerta(
            alerta_id=str(uuid4()),
            severidade=rota.severidade,
            destinatarios=list(rota.destinatarios),
            canais=list(rota.canais),
            titulo=renderizar(rota.titulo, evento),
            mensagem=renderizar(rota.mensagem, evento),
            evento_id=evento.evento_id,
            origem=evento.origem,
            session_id=evento.session_id,
            capturado_em=(
                ler_horario(evento.capturado_em, "captured_at")
                if evento.capturado_em is not None
                else None
            ),
            correlacao_id=evento.evento_id,
            versao_roteamento=(
                self.roteador.versao if self.roteador else None
            ),
        )

        # Salva o alerta e registra sua criação.
        self.repository.salvar(alerta)

        self._publicar(alerta)

        return alerta

    def processar_evento_roteado(
        self,
        evento: EventoQualificado,
    ) -> Alerta | None:
        """
        Processa um evento usando o roteador configurado.
        Retorna None quando o evento não gera alerta.
        """

        evento.validar()

        if self.roteador is None:
            raise ValueError(
                "O serviço não possui um roteador configurado."
            )

        rota = self.roteador.resolver(evento)

        if rota is None:
            return None

        return self.processar_evento(evento, rota)

    def criar_alerta(
        self,
        titulo: str,
        mensagem: str,
        severidade: str,
        destinatarios: list[str],
        canais: list[str],
        evento_id: str | None = None,
        clip_id: str | None = None,
        correlacao_id: str | None = None,
    ) -> Alerta:
        """
        Alerta de negócio pedido por uma aplicação
        (ods.s3.alert.command), sem passar pelo ROUTING.
        """

        alerta = Alerta(
            alerta_id=str(uuid4()),
            severidade=severidade,
            destinatarios=list(destinatarios),
            canais=list(canais),
            titulo=titulo,
            mensagem=mensagem,
            evento_id=evento_id,
            clip_id=clip_id,
            correlacao_id=correlacao_id,
        )

        self.repository.salvar(alerta, indexar_evento=False)

        self._publicar(alerta)

        return alerta

    def reconhecer_alerta(
        self,
        alerta_id: str,
        autor_id: str,
        motivo: str | None = None,
    ) -> Alerta:
        """
        Registra que um responsável confirmou ter visto o alerta.
        """

        return self._mudar_estado(
            alerta_id, autor_id, "ACKNOWLEDGED", motivo
        )

    def silenciar_alerta(
        self,
        alerta_id: str,
        autor_id: str,
        silenciar_ate: datetime,
        motivo: str | None = None,
    ) -> Alerta:
        """
        Silencia o alerta até silenciar_ate (mute_until).

        Pendente: o que acontece quando o prazo vence.
        Por ora o alerta continua MUTED.
        """

        return self._mudar_estado(
            alerta_id, autor_id, "MUTED", motivo, silenciar_ate
        )

    def encerrar_alerta(
        self,
        alerta_id: str,
        autor_id: str,
        motivo: str | None = None,
    ) -> Alerta:
        """
        Encerra o alerta. CLOSED é um estado final.
        """

        return self._mudar_estado(alerta_id, autor_id, "CLOSED", motivo)

    def consultar_alertas(
        self,
        desde: datetime | None = None,
        ate: datetime | None = None,
        estado: str | None = None,
        severidade: str | None = None,
        limite: int = 100,
    ) -> tuple[list[Alerta], datetime | None]:
        """
        Histórico de alertas (ods.s3.alerts.query).
        """

        return self.repository.listar(
            desde, ate, estado, severidade, limite
        )

    def _mudar_estado(
        self,
        alerta_id: str,
        autor_id: str,
        novo_estado: str,
        motivo: str | None = None,
        silenciar_ate: datetime | None = None,
    ) -> Alerta:
        """
        Aplica uma transição permitida e registra no histórico.

        Uma transição não permitida (inclusive repetir o
        mesmo comando com outro message_id) gera
        INVALID_TRANSITION e não altera nada.
        """

        alerta = self.repository.buscar_por_id(alerta_id)

        if alerta is None:
            raise ErroS3(ALERT_NOT_FOUND, "Alerta não encontrado.")

        if alerta.estado not in TRANSICOES[novo_estado]:
            raise ErroS3(
                INVALID_TRANSITION,
                f"Transição inválida: {alerta.estado} → {novo_estado}.",
            )

        registro = RegistroHistorico(
            alerta_id=alerta.alerta_id,
            evento_id=alerta.evento_id,
            acao=novo_estado,
            autor_id=autor_id,
            motivo=motivo,
            silenciado_ate=silenciar_ate,
        )

        alerta.estado = novo_estado

        if novo_estado == "ACKNOWLEDGED":
            alerta.reconhecido_por = autor_id
            alerta.reconhecido_em = registro.registrado_em
        elif novo_estado == "MUTED":
            alerta.silenciado_ate = silenciar_ate
        elif novo_estado == "CLOSED":
            alerta.encerrado_por = autor_id
            alerta.encerrado_em = registro.registrado_em

        # Grava estado e histórico juntos; se algo for
        # inválido, nada é alterado.
        self.repository.atualizar(alerta, registro)

        self._publicar(alerta)

        return alerta

    def _publicar(self, alerta: Alerta) -> None:
        """
        Envia o estado atual do alerta às aplicações
        (ods.s3.alert). Se o publicador falhar, o alerta
        já está salvo: limitação conhecida, resolvida
        junto com a persistência.
        """

        if self.publicador is None:
            return

        self.publicador.publicar(
            alerta_para_json(
                alerta,
                sequence=self._sequencia.proximo(alerta.session_id),
            )
        )
