
from dataclasses import dataclass

from s3.contracts import EventoQualificado

"configuração e roteador"
'Decide as configurações do alerta (severidade, destinatário e canais)'

@dataclass(frozen=True)
class ConfiguracaoRoteamento:
    """
    Configuração fornecida pela aplicação.

    Define como determinado tipo de evento
    deve ser encaminhado pelo S3.
    """

    severidade: str
    destinatarios: tuple[str, ...]
    canais: tuple[str, ...]

    def __post_init__(self) -> None:

        if not self.severidade.strip():
            raise ValueError(
                "A severidade é obrigatória."
            )

        if not self.destinatarios:
            raise ValueError(
                "É necessário informar destinatários."
            )

        if any(
            not destinatario.strip()
            for destinatario in self.destinatarios
        ):
            raise ValueError(
                "Os destinatários devem ser válidos."
            )

        if not self.canais:
            raise ValueError(
                "É necessário informar canais."
            )

        canais_permitidos = {
            "SOM",
            "TELA",
            "PUSH"
        }

        if any(
            canal not in canais_permitidos
            for canal in self.canais
        ):
            raise ValueError(
                "Canal de notificação inválido."
            )


class RoteadorAlertas:
    """
    Resolve a configuração de roteamento
    correspondente a um evento qualificado.
    """

    def __init__(
        self,
        regras: dict[str, ConfiguracaoRoteamento]
    ) -> None:

        if not regras:
            raise ValueError(
                "É necessário configurar regras."
            )

        self._regras = dict(regras)

    def resolver(
        self,
        evento: EventoQualificado
    ) -> ConfiguracaoRoteamento:

        evento.validar()

        configuracao = self._regras.get(
            evento.tipo
        )

        if configuracao is None:
            raise ValueError(
                f"Não existe roteamento para: {evento.tipo}"
            )

        return configuracao