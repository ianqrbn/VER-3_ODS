
from s3.alert import Alerta
from s3.history import RegistroHistorico

"armazenamento em memória"
' Salva o alerta'

class AlertRepository:
    """
    Repositório em memória para alertas e histórico.

    Implementação provisória:
    os dados são perdidos ao encerrar o processo.
    """

    def __init__(self) -> None:
        self._alertas: dict[str, Alerta] = {}
        self._eventos: dict[str, str] = {}

        self._historicos: dict[
            str, list[RegistroHistorico]
        ] = {}

    def salvar(self, alerta: Alerta) -> None:
        """
        Salva um alerta e registra sua criação.
        """

        alerta.validar()

        if alerta.alerta_id in self._alertas:
            raise ValueError(
                "Já existe um alerta com este ID."
            )

        if alerta.evento_id in self._eventos:
            raise ValueError(
                "Já existe um alerta para este evento."
            )

        # Prepara o registro antes de modificar os dados.
        registro = RegistroHistorico(
            alerta_id=alerta.alerta_id,
            evento_id=alerta.evento_id,
            acao="CRIADO",
            registrado_em=alerta.criado_em
        )

        # Armazena o alerta.
        self._alertas[alerta.alerta_id] = alerta

        # Associa o evento ao alerta.
        self._eventos[alerta.evento_id] = alerta.alerta_id

        # Cria o histórico inicial.
        self._historicos[alerta.alerta_id] = [registro]

    def buscar_por_id(
        self,
        alerta_id: str
    ) -> Alerta | None:
        """
        Busca um alerta pelo ID.
        """

        return self._alertas.get(alerta_id)

    def buscar_por_evento(
        self,
        evento_id: str
    ) -> Alerta | None:
        """
        Busca o alerta associado ao evento.
        """

        alerta_id = self._eventos.get(evento_id)

        if alerta_id is None:
            return None

        return self._alertas.get(alerta_id)

    def registrar_historico(
        self,
        registro: RegistroHistorico
    ) -> None:
        """
        Adiciona uma ação ao histórico de um alerta.
        """

        alerta = self.buscar_por_id(
            registro.alerta_id
        )

        if alerta is None:
            raise ValueError(
                "Não existe alerta para este registro."
            )

        if registro.evento_id != alerta.evento_id:
            raise ValueError(
                "O evento do registro não corresponde ao alerta."
            )

        if registro.acao == "CRIADO":
            raise ValueError(
                "A criação já é registrada automaticamente."
            )

        historico = self._historicos[registro.alerta_id]

        if any(
            item.registro_id == registro.registro_id
            for item in historico
        ):
            raise ValueError(
                "Este registro já existe no histórico."
            )

        historico.append(registro)

    def buscar_historico(
        self,
        alerta_id: str
    ) -> tuple[RegistroHistorico, ...]:
        """
        Retorna os registros associados ao alerta.
        """

        if alerta_id not in self._alertas:
            raise ValueError(
                "Alerta não encontrado."
            )

        return tuple(
            self._historicos[alerta_id]
        )