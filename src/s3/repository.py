
from copy import deepcopy
from datetime import datetime

from s3.alert import Alerta
from s3.history import RegistroHistorico

"armazenamento em memória"
' Salva o alerta'


class AlertRepository:
    """
    Repositório em memória para alertas, histórico
    e mensagens já processadas.

    Implementação provisória:
    os dados são perdidos ao encerrar o processo.

    Devolve sempre cópias: o estado só muda por
    atualizar(), que exige um registro de histórico.
    """

    def __init__(self) -> None:
        self._alertas: dict[str, Alerta] = {}
        self._eventos: dict[str, str] = {}

        self._historicos: dict[
            str, list[RegistroHistorico]
        ] = {}

        # message_id → reply já enviada (None em eventos).
        self._mensagens: dict[str, dict | None] = {}

    def salvar(
        self,
        alerta: Alerta,
        indexar_evento: bool = True,
    ) -> None:
        """
        Salva um alerta e registra sua criação.

        indexar_evento=False para alertas criados por
        comando, que citam um event_id sem serem o
        alerta daquele evento.
        """

        alerta.validar()

        if alerta.alerta_id in self._alertas:
            raise ValueError(
                "Já existe um alerta com este ID."
            )

        if indexar_evento:
            if alerta.evento_id is None:
                raise ValueError(
                    "Um alerta de evento precisa do event_id."
                )

            if alerta.evento_id in self._eventos:
                raise ValueError(
                    "Já existe um alerta para este evento."
                )

        # Prepara o registro antes de modificar os dados.
        registro = RegistroHistorico(
            alerta_id=alerta.alerta_id,
            evento_id=alerta.evento_id,
            acao="CREATED",
            registrado_em=alerta.criado_em,
        )

        self._alertas[alerta.alerta_id] = deepcopy(alerta)

        if indexar_evento:
            self._eventos[alerta.evento_id] = alerta.alerta_id

        self._historicos[alerta.alerta_id] = [registro]

    def buscar_por_id(
        self,
        alerta_id: str
    ) -> Alerta | None:
        """
        Busca um alerta pelo ID (cópia).
        """

        alerta = self._alertas.get(alerta_id)

        return deepcopy(alerta) if alerta is not None else None

    def buscar_por_evento(
        self,
        evento_id: str
    ) -> Alerta | None:
        """
        Busca o alerta associado ao evento (cópia).
        """

        alerta_id = self._eventos.get(evento_id)

        if alerta_id is None:
            return None

        return self.buscar_por_id(alerta_id)

    def atualizar(
        self,
        alerta: Alerta,
        registro: RegistroHistorico,
    ) -> None:
        """
        Grava o novo estado do alerta junto com a ação
        que o causou. Valida tudo antes de alterar.
        """

        atual = self._alertas.get(alerta.alerta_id)

        if atual is None:
            raise ValueError(
                "Não existe alerta para este registro."
            )

        if registro.alerta_id != alerta.alerta_id:
            raise ValueError(
                "O registro não corresponde ao alerta."
            )

        if registro.evento_id != atual.evento_id:
            raise ValueError(
                "O evento do registro não corresponde ao alerta."
            )

        if registro.acao == "CREATED":
            raise ValueError(
                "A criação já é registrada automaticamente."
            )

        if registro.acao != alerta.estado:
            raise ValueError(
                "A ação do registro deve ser o novo estado."
            )

        historico = self._historicos[alerta.alerta_id]

        if any(
            item.registro_id == registro.registro_id
            for item in historico
        ):
            raise ValueError(
                "Este registro já existe no histórico."
            )

        alerta.validar()

        historico.append(registro)
        self._alertas[alerta.alerta_id] = deepcopy(alerta)

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

    def listar(
        self,
        desde: datetime | None = None,
        ate: datetime | None = None,
        estado: str | None = None,
        severidade: str | None = None,
        limite: int = 100,
    ) -> tuple[list[Alerta], datetime | None]:
        """
        Alertas criados em [desde, ate), em ordem de criação.

        Retorna a página e o criado_em do próximo alerta
        (next_from_at), ou None se não houver mais.
        """

        encontrados = sorted(
            (
                alerta
                for alerta in self._alertas.values()
                if (desde is None or alerta.criado_em >= desde)
                and (ate is None or alerta.criado_em < ate)
                and (estado is None or alerta.estado == estado)
                and (
                    severidade is None
                    or alerta.severidade == severidade
                )
            ),
            key=lambda alerta: alerta.criado_em,
        )

        pagina = [deepcopy(alerta) for alerta in encontrados[:limite]]

        proximo = (
            encontrados[limite].criado_em
            if len(encontrados) > limite
            else None
        )

        return pagina, proximo

    def mensagem_processada(self, message_id: str) -> bool:
        return message_id in self._mensagens

    def resposta_registrada(self, message_id: str) -> dict | None:
        return deepcopy(self._mensagens.get(message_id))

    def registrar_mensagem(
        self,
        message_id: str,
        resposta: dict | None = None,
    ) -> None:
        """
        Marca a mensagem como processada; em comandos,
        guarda a reply para devolvê-la se o comando
        chegar de novo (idempotência pelo message_id).
        """

        self._mensagens[message_id] = deepcopy(resposta)
