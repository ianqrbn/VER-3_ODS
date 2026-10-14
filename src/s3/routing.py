
from dataclasses import dataclass

from s3.alert import (
    validar_canais,
    validar_destinatarios,
    validar_severidade,
)
from s3.contracts import STATUS_EVENTO, EventoQualificado

"configuração e roteador"
'Artefato ROUTING (Especificação 1.0, seção 8): tipo de evento → alerta'

CAMPOS_ROTA = (
    "event_type",
    "min_status",
    "severity",
    "recipients",
    "channels",
    "title",
    "message",
    "capture",
)


@dataclass(frozen=True)
class ConfiguracaoRoteamento:
    """
    Uma rota do artefato ROUTING.

    titulo e mensagem são modelos com {campo},
    substituídos pelos campos do evento.
    """

    severidade: str                       # severity
    destinatarios: tuple[str, ...]        # recipients
    canais: tuple[str, ...]               # channels
    titulo: str                           # title
    mensagem: str                         # message
    status_minimo: str = "CONFIRMED"      # min_status
    captura: bool = False                 # capture

    def __post_init__(self) -> None:

        validar_severidade(self.severidade)
        validar_destinatarios(self.destinatarios)
        validar_canais(self.canais)

        # Listas viram tuplas: a configuração é imutável.
        object.__setattr__(
            self, "destinatarios", tuple(self.destinatarios)
        )
        object.__setattr__(self, "canais", tuple(self.canais))

        for valor, campo in (
            (self.titulo, "title"),
            (self.mensagem, "message"),
        ):
            if not isinstance(valor, str) or not valor.strip():
                raise ValueError(f"{campo} é obrigatório.")

        if self.status_minimo not in STATUS_EVENTO:
            raise ValueError(
                f"min_status inválido: {self.status_minimo}"
            )

        if not isinstance(self.captura, bool):
            raise ValueError("capture deve ser booleano.")

    def aceita(self, status: str) -> bool:
        """
        min_status CONFIRMED roteia só eventos confirmados;
        UNCERTAIN roteia também os eventos em dúvida.
        """

        return status == "CONFIRMED" or self.status_minimo == "UNCERTAIN"


class _ValoresModelo(dict):
    """Mantém {campo} quando o evento não tem o campo."""

    def __missing__(self, chave: str) -> str:
        return "{" + chave + "}"


def renderizar(modelo: str, evento: EventoQualificado) -> str:
    """
    Substitui {campo} pelos campos do evento, com os
    nomes do contrato (equipment_item, zone_id...).
    """

    valores = _ValoresModelo(evento.detalhes)

    duracao_s = (
        evento.duracao_ms // 1000
        if evento.duracao_ms is not None
        else None
    )

    for chave, valor in (
        ("event_id", evento.evento_id),
        ("event_type", evento.tipo),
        ("rule_id", evento.regra_id),
        ("status", evento.status),
        ("entity_id", evento.entidade_id),
        ("class", evento.classe),
        ("zone_id", evento.zona_id),
        ("equipment_item", evento.equipamento),
        ("confidence", evento.confianca),
        ("started_at", evento.iniciado_em),
        ("duration_ms", evento.duracao_ms),
        ("duration_s", duracao_s),
        ("source_id", evento.origem),
    ):
        if valor is not None:
            valores[chave] = valor

    try:
        return modelo.format_map(valores)
    except (ValueError, AttributeError, IndexError, KeyError):
        # Modelo mal formado: usa o texto como está.
        return modelo


class RoteadorAlertas:
    """
    Resolve a rota de um evento qualificado.
    """

    def __init__(
        self,
        regras: dict[str, ConfiguracaoRoteamento],
        versao: str | None = None,
    ) -> None:

        if not regras:
            raise ValueError(
                "É necessário configurar regras."
            )

        self._regras = dict(regras)

        # artifact_version do ROUTING carregado.
        self.versao = versao

    @classmethod
    def de_artefato(
        cls,
        conteudo: dict,
        versao: str,
    ) -> "RoteadorAlertas":
        """
        Carrega o conteúdo do artefato ROUTING:
        { "routes": [ {event_type, min_status, ...} ] }
        """

        if not isinstance(conteudo, dict):
            raise ValueError("O artefato ROUTING deve ser um objeto.")

        rotas = conteudo.get("routes")

        if not isinstance(rotas, list) or not rotas:
            raise ValueError("O artefato ROUTING precisa de routes.")

        regras: dict[str, ConfiguracaoRoteamento] = {}

        for rota in rotas:
            if not isinstance(rota, dict):
                raise ValueError("Cada rota deve ser um objeto.")

            for campo in CAMPOS_ROTA:
                if campo not in rota:
                    raise ValueError(f"Rota sem o campo {campo}.")

            tipo = rota["event_type"]

            if tipo in regras:
                raise ValueError(f"Rota repetida para {tipo}.")

            regras[tipo] = ConfiguracaoRoteamento(
                severidade=rota["severity"],
                destinatarios=rota["recipients"],
                canais=rota["channels"],
                titulo=rota["title"],
                mensagem=rota["message"],
                status_minimo=rota["min_status"],
                captura=rota["capture"],
            )

        return cls(regras, versao=versao)

    def resolver(
        self,
        evento: EventoQualificado
    ) -> ConfiguracaoRoteamento | None:
        """
        Retorna a rota do evento, ou None quando o tipo
        não tem rota ou o status está abaixo de min_status.
        Isso não é erro: a build recebe todos os eventos
        do S2, e só alguns viram alerta.
        """

        evento.validar()

        configuracao = self._regras.get(evento.tipo)

        if configuracao is None:
            return None

        if not configuracao.aceita(evento.status):
            return None

        return configuracao
