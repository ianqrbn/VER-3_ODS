
import json

from s3.alert import ESTADOS, SEVERIDADES
from s3.envelope import (
    PERFIL_CMD,
    decodificar,
    formatar_horario,
    ler_horario,
    montar_envelope,
    validar_envelope,
)
from s3.errors import INVALID_MESSAGE, INVALID_PAYLOAD, ErroS3
from s3.output import payload_alerta
from s3.service import AlertService

"comandos e consultas"
'Atende ods.s3.alert.command, ods.s3.alert_action.command e ods.s3.alerts.query'

SCHEMA_CRIAR = "ods.s3.alert.command"
SCHEMA_ACAO = "ods.s3.alert_action.command"
SCHEMA_CONSULTA = "ods.s3.alerts.query"

DESTINO = "S3"

LIMITE_PADRAO = 100
LIMITE_MAXIMO = 500


def _texto(payload: dict, campo: str, obrigatorio: bool = True):
    valor = payload.get(campo)

    if valor is None and not obrigatorio:
        return None

    if not isinstance(valor, str) or not valor.strip():
        raise ErroS3(INVALID_PAYLOAD, f"{campo} deve ser um texto não vazio.")

    return valor


def _horario(payload: dict, campo: str, obrigatorio: bool = True):
    valor = payload.get(campo)

    if valor is None and not obrigatorio:
        return None

    return ler_horario(valor, campo)


def _schema_reply(schema: str) -> str:
    """ods.s3.alert_action.command → ods.s3.alert_action.reply"""

    return schema.rsplit(".", 1)[0] + ".reply"


class ProcessadorComandos:
    """
    Recebe comandos e consultas dirigidos ao S3
    e devolve a reply (texto JSON) a publicar.

    Idempotência pelo message_id: um comando repetido
    recebe a mesma reply, sem novo efeito.
    """

    def __init__(self, service: AlertService) -> None:
        self.service = service

        self._tratadores = {
            SCHEMA_CRIAR: ("command", self._criar),
            SCHEMA_ACAO: ("command", self._acao),
            SCHEMA_CONSULTA: ("query", self._consultar),
        }

    def receber(self, mensagem: str | bytes) -> str:
        """
        Processa um comando ou consulta.

        Envelope inválido gera ErroS3 (sem reply: não há
        como responder a quem não se identificou). Erro no
        payload ou na regra vira reply com status ERROR.
        """

        dados = decodificar(mensagem)
        schema = dados.get("schema")

        if schema not in self._tratadores:
            raise ErroS3(INVALID_MESSAGE, f"schema inesperado: {schema}")

        message_type, tratador = self._tratadores[schema]

        payload = validar_envelope(dados, schema, message_type, PERFIL_CMD)

        if dados["target"] != DESTINO:
            raise ErroS3(
                INVALID_MESSAGE, f"Comando para outro destino: {dados['target']}"
            )

        message_id = dados["message_id"]
        repository = self.service.repository

        anterior = repository.resposta_registrada(message_id)

        if anterior is not None:
            return json.dumps(anterior, ensure_ascii=False)

        try:
            corpo = tratador(payload, message_id)
        except ErroS3 as erro:
            corpo = self._erro(erro.codigo, str(erro))
        except ValueError as erro:
            corpo = self._erro(INVALID_PAYLOAD, str(erro))

        resposta = montar_envelope(
            "reply",
            _schema_reply(schema),
            corpo,
            correlation_id=message_id,
        )

        # Consultas não alteram estado; só comandos
        # precisam devolver a mesma reply se repetidos.
        if message_type == "command":
            repository.registrar_mensagem(message_id, resposta)

        return json.dumps(resposta, ensure_ascii=False)

    @staticmethod
    def _erro(codigo: str, mensagem: str) -> dict:
        return {
            "status": "ERROR",
            "error": {"code": codigo, "message": mensagem},
        }

    def _criar(self, payload: dict, message_id: str) -> dict:
        """ods.s3.alert.command"""

        for campo in ("recipients", "channels", "severity"):
            if campo not in payload:
                raise ErroS3(
                    INVALID_PAYLOAD, f"Campo obrigatório ausente: {campo}"
                )

        alerta = self.service.criar_alerta(
            titulo=_texto(payload, "title"),
            mensagem=_texto(payload, "message"),
            severidade=payload["severity"],
            destinatarios=payload["recipients"],
            canais=payload["channels"],
            evento_id=_texto(payload, "event_id", obrigatorio=False),
            clip_id=_texto(payload, "clip_id", obrigatorio=False),
            correlacao_id=message_id,
        )

        return {"status": "OK", "alert_id": alerta.alerta_id}

    def _acao(self, payload: dict, message_id: str) -> dict:
        """ods.s3.alert_action.command"""

        alerta_id = _texto(payload, "alert_id")
        acao = payload.get("action")
        autor = _texto(payload, "actor")
        motivo = _texto(payload, "reason", obrigatorio=False)

        # Contrato: actor = user:<id>.
        if not autor.startswith("user:") or not autor[5:].strip():
            raise ErroS3(
                INVALID_PAYLOAD, f"actor deve ser user:<id>: {autor!r}"
            )

        if acao == "ACKNOWLEDGE":
            alerta = self.service.reconhecer_alerta(alerta_id, autor, motivo)
        elif acao == "MUTE":
            alerta = self.service.silenciar_alerta(
                alerta_id,
                autor,
                _horario(payload, "mute_until"),
                motivo,
            )
        elif acao == "CLOSE":
            alerta = self.service.encerrar_alerta(alerta_id, autor, motivo)
        else:
            raise ErroS3(INVALID_PAYLOAD, f"action inválida: {acao!r}")

        return {
            "status": "OK",
            "alert_id": alerta.alerta_id,
            "state": alerta.estado,
        }

    def _consultar(self, payload: dict, message_id: str) -> dict:
        """ods.s3.alerts.query"""

        estado = payload.get("state")
        severidade = payload.get("severity")
        limite = payload.get("limit", LIMITE_PADRAO)

        if estado is not None and estado not in ESTADOS:
            raise ErroS3(INVALID_PAYLOAD, f"state inválido: {estado!r}")

        if severidade is not None and severidade not in SEVERIDADES:
            raise ErroS3(
                INVALID_PAYLOAD, f"severity inválida: {severidade!r}"
            )

        if (
            isinstance(limite, bool)
            or not isinstance(limite, int)
            or not 1 <= limite <= LIMITE_MAXIMO
        ):
            raise ErroS3(
                INVALID_PAYLOAD,
                f"limit deve estar entre 1 e {LIMITE_MAXIMO}.",
            )

        alertas, proximo = self.service.consultar_alertas(
            desde=_horario(payload, "from_at", obrigatorio=False),
            ate=_horario(payload, "to_at", obrigatorio=False),
            estado=estado,
            severidade=severidade,
            limite=limite,
        )

        corpo = {
            "status": "OK",
            "alerts": [payload_alerta(alerta) for alerta in alertas],
        }

        # Só presente quando há próxima página.
        if proximo is not None:
            corpo["next_from_at"] = formatar_horario(proximo)

        return corpo
