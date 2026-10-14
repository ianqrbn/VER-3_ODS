
import json
from datetime import datetime, timezone
from uuid import uuid4

from s3.errors import INVALID_MESSAGE, INVALID_PAYLOAD, ErroS3

"envelope comum"
'Monta e valida o envelope de 13 campos (Especificação 1.0, seção 3)'

PRODUTOR = "S3"
VERSAO_SCHEMA = "1.0"

# Aceita qualquer MINOR do MAJOR conhecido (seção 2, regra 8).
MAJOR_SUPORTADO = "1."

# Presentes em toda mensagem.
CAMPOS_FIXOS = (
    "message_type",
    "message_id",
    "schema",
    "schema_version",
    "producer",
    "published_at",
)

# Campos obrigatórios além dos fixos, por perfil.
PERFIL_EV_SERVICO = ("captured_at", "session_id", "sequence")
PERFIL_CMD = ("target",)
PERFIL_RPL = ("correlation_id",)

# Ordem dos campos de contexto na mensagem montada.
CAMPOS_CONTEXTO = (
    "target",
    "correlation_id",
    "captured_at",
    "source_id",
    "session_id",
    "sequence",
    "artifact_version",
)


def agora() -> datetime:
    """Horário atual em UTC."""

    return datetime.now(timezone.utc)


def formatar_horario(horario: datetime) -> str:
    """
    ISO 8601 em UTC com milissegundos:
    2026-09-23T14:29:59.870Z.
    """

    if horario.tzinfo is None or horario.utcoffset() is None:
        raise ValueError(
            "O horário precisa conter fuso horário."
        )

    return (
        horario.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def ler_horario(
    valor: object,
    campo: str,
    codigo: str = INVALID_PAYLOAD,
) -> datetime:
    """
    Converte um texto ISO 8601 com fuso em datetime.
    """

    if not isinstance(valor, str) or not valor.strip():
        raise ErroS3(codigo, f"{campo} deve ser um horário ISO 8601.")

    try:
        # "Z" só é aceito pelo fromisoformat a partir do Python 3.11.
        horario = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as erro:
        raise ErroS3(
            codigo, f"{campo} não está em ISO 8601: {valor}"
        ) from erro

    if horario.tzinfo is None or horario.utcoffset() is None:
        raise ErroS3(codigo, f"{campo} precisa conter fuso horário.")

    return horario


def decodificar(mensagem: str | bytes) -> dict:
    """
    Converte o texto recebido em objeto JSON.
    O Kafka entrega bytes; os testes usam texto.
    """

    try:
        if isinstance(mensagem, bytes):
            mensagem = mensagem.decode("utf-8")

        dados = json.loads(mensagem)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as erro:
        raise ErroS3(INVALID_MESSAGE, "Mensagem JSON inválida.") from erro

    if not isinstance(dados, dict):
        raise ErroS3(
            INVALID_MESSAGE, "A mensagem deve conter um objeto JSON."
        )

    return dados


def validar_envelope(
    dados: dict,
    schema: str,
    message_type: str,
    obrigatorios: tuple[str, ...] = (),
) -> dict:
    """
    Valida o envelope e retorna o payload.
    """

    for campo in CAMPOS_FIXOS + obrigatorios + ("payload",):
        if dados.get(campo) is None:
            raise ErroS3(
                INVALID_MESSAGE, f"Campo obrigatório ausente: {campo}"
            )

    if dados["message_type"] != message_type:
        raise ErroS3(
            INVALID_MESSAGE,
            f"message_type inesperado: {dados['message_type']}",
        )

    if dados["schema"] != schema:
        raise ErroS3(
            INVALID_MESSAGE, f"schema inesperado: {dados['schema']}"
        )

    if not str(dados["schema_version"]).startswith(MAJOR_SUPORTADO):
        raise ErroS3(
            INVALID_MESSAGE,
            f"Versão não suportada: {dados['schema_version']}",
        )

    for campo in ("message_id", "producer"):
        valor = dados[campo]

        if not isinstance(valor, str) or not valor.strip():
            raise ErroS3(INVALID_MESSAGE, f"{campo} inválido.")

    ler_horario(dados["published_at"], "published_at", INVALID_MESSAGE)

    if "captured_at" in obrigatorios:
        ler_horario(dados["captured_at"], "captured_at", INVALID_MESSAGE)

    if "sequence" in obrigatorios:
        sequencia = dados["sequence"]

        if (
            isinstance(sequencia, bool)
            or not isinstance(sequencia, int)
            or sequencia < 0
        ):
            raise ErroS3(INVALID_MESSAGE, "sequence inválido.")

    if not isinstance(dados["payload"], dict):
        raise ErroS3(
            INVALID_MESSAGE, "O payload deve ser um objeto JSON."
        )

    return dados["payload"]


def montar_envelope(
    message_type: str,
    schema: str,
    payload: dict,
    *,
    publicado_em: datetime | None = None,
    message_id: str | None = None,
    **contexto: object,
) -> dict:
    """
    Monta uma mensagem publicada pelo S3.

    Campos de contexto com valor None são omitidos.
    """

    envelope = {
        "message_type": message_type,
        "message_id": message_id or str(uuid4()),
        "schema": schema,
        "schema_version": VERSAO_SCHEMA,
        "producer": PRODUTOR,
        "published_at": formatar_horario(publicado_em or agora()),
    }

    for campo in CAMPOS_CONTEXTO:
        valor = contexto.get(campo)

        if valor is None:
            continue

        if isinstance(valor, datetime):
            valor = formatar_horario(valor)

        envelope[campo] = valor

    envelope["payload"] = payload

    return envelope


class Sequencia:
    """
    Contador crescente por sessão, a partir de 0
    (campo sequence do envelope).
    """

    def __init__(self) -> None:
        self._contadores: dict[str | None, int] = {}

    def proximo(self, session_id: str | None) -> int:
        valor = self._contadores.get(session_id, 0)
        self._contadores[session_id] = valor + 1
        return valor
