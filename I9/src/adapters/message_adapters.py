"""
Adaptadores de mensagens (EV-SINAL) independentes do transporte.

Substituem os mocks quando as mensagens reais chegam do barramento (B3). O
consumidor Kafka (ou outro transporte oficial) só precisa entregar o corpo de
cada mensagem — `dict`, `str` ou `bytes` JSON — e o produtor só precisa expor
uma função `send(topic, key, value)`:

* `MessageIngestionAdapter`: lê `ods.i1.detections` de um iterável de mensagens;
* `MessageCalibrationAdapter`: mantém a última `ods.i3.calibration` por `source_id`;
* `MessagePublisherAdapter`: serializa `ods.i9.ppe_compliance` e entrega ao `send`.

Mensagens inválidas não derrubam o consumidor: são registradas em `rejected`
com o motivo, para rastreabilidade.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple, Union

from src.domain.models import (
    COMPLIANCE_SCHEMA,
    Calibration,
    ComplianceEvent,
    DetectionFrame,
)

RawMessage = Union[Mapping[str, Any], str, bytes]


def decode_message(message: RawMessage) -> Mapping[str, Any]:
    """Converte o corpo bruto da mensagem em dicionário."""
    if isinstance(message, bytes):
        message = message.decode("utf-8")
    if isinstance(message, str):
        message = json.loads(message)
    if not isinstance(message, Mapping):
        raise ValueError("mensagem: esperado objeto JSON")
    return message


class MessageIngestionAdapter:
    """Consome `ods.i1.detections` de uma fonte de mensagens (ex.: consumidor Kafka)."""

    def __init__(self, messages: Iterable[RawMessage]):
        self._messages: Iterator[RawMessage] = iter(messages)
        self.rejected: List[Tuple[RawMessage, str]] = []

    def get_next_event(self) -> Optional[DetectionFrame]:
        for message in self._messages:
            try:
                return DetectionFrame.from_event(decode_message(message))
            except ValueError as exc:  # json.JSONDecodeError herda de ValueError
                self.rejected.append((message, str(exc)))
        return None


class MessageCalibrationAdapter:
    """Guarda a calibração mais recente recebida do I3 para cada câmera."""

    def __init__(self, messages: Iterable[RawMessage] = ()):
        self._by_source: Dict[str, Calibration] = {}
        self.rejected: List[Tuple[RawMessage, str]] = []
        for message in messages:
            self.on_message(message)

    def on_message(self, message: RawMessage) -> Optional[Calibration]:
        """Callback para o consumidor de `ods.i3.calibration`."""
        try:
            calibration = Calibration.from_event(decode_message(message))
        except ValueError as exc:
            self.rejected.append((message, str(exc)))
            return None
        self._by_source[calibration.source_id] = calibration
        return calibration

    def get_calibration(self, source_id: str) -> Optional[Calibration]:
        return self._by_source.get(source_id)


class MessagePublisherAdapter:
    """Publica `ods.i9.ppe_compliance` por meio de uma função `send(topic, key, value)`.

    A chave da mensagem é o `source_id`, para preservar a ordem dos quadros de uma
    mesma câmera em uma partição.
    """

    def __init__(self, send: Callable[[str, str, str], Any], topic: str = COMPLIANCE_SCHEMA):
        self._send = send
        self.topic = topic

    def publish_event(self, event: ComplianceEvent) -> None:
        for body in event.messages():
            self._send(self.topic, event.source_id, json.dumps(body, ensure_ascii=False))
