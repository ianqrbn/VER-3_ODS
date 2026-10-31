"""
Orquestração do componente I9 por quadro.

O pipeline é deliberadamente burro: busca um evento de detecções do I1, garante
a calibração da câmera (I3), executa a associação geométrica, infere os estados
relacionais e publica `ods.i9.ppe_compliance`. Não há estado acumulado entre
quadros — o cruzamento temporal é responsabilidade do S2.
"""

from __future__ import annotations

from typing import Optional

from src.core.calibration import CalibrationStore
from src.core.inference import RelationInferenceModule
from src.core.pairing import PairingModule
from src.domain.catalog import PpeCatalog
from src.domain.models import ComplianceEvent, DetectionFrame
from src.domain.policy import EquipmentPolicy
from src.ports.calibration_port import CalibrationPort
from src.ports.ingestion_port import IngestionPort
from src.ports.output_port import OutputPort


class I9Pipeline:
    def __init__(
        self,
        ingestion_port: IngestionPort,
        output_port: OutputPort,
        calibration_port: CalibrationPort,
        pairing_module: PairingModule,
        inference_module: RelationInferenceModule,
        policy: EquipmentPolicy,
    ):
        self.ingestion_port = ingestion_port
        self.output_port = output_port
        self.calibration_port = calibration_port
        self.pairing_module = pairing_module
        self.inference_module = inference_module
        self.policy = policy
        self.base_policy = policy

        if pairing_module.calibration_store is None:
            raise ValueError("o PairingModule precisa de um CalibrationStore")

    @property
    def calibration_store(self) -> CalibrationStore:
        return self.pairing_module.calibration_store

    def apply_catalog(self, catalog: PpeCatalog) -> EquipmentPolicy:
        """Troca a lista de EPIs pela do `PPE_CATALOG` do A5, a partir do próximo quadro.

        A política é sempre derivada da configuração base (parâmetros do motor),
        nunca do catálogo anterior. Um catálogo inválido levanta `ValueError` e
        mantém a política em uso.
        """
        policy = self.base_policy.with_catalog(catalog)
        self.policy = policy
        self.pairing_module.policy = policy
        self.inference_module.policy = policy
        return policy

    def run_once(self) -> Optional[ComplianceEvent]:
        """Processa o próximo quadro. Retorna None quando não há mais dados."""
        frame = self.ingestion_port.get_next_event()
        if frame is None:
            return None
        return self.process(frame)

    def process(self, frame: DetectionFrame) -> ComplianceEvent:
        self._ensure_calibration(frame)

        pairing = self.pairing_module.pair(frame)
        evaluations = self.inference_module.infer(pairing)

        event = ComplianceEvent(
            source_id=frame.source_id,
            session_id=frame.session_id,
            captured_at=frame.captured_at,
            sequence=frame.sequence,
            frame_index=frame.frame_index,
            image_width=frame.image_width,
            image_height=frame.image_height,
            artifact_version=self.policy.artifact_version,
            catalog_version=self.policy.catalog_version,
            calibration=self.calibration_store.status(frame.source_id),
            relations=tuple(evaluations),
            unassociated_equipment=tuple(pairing.unassociated_equipment),
            ignored_detections=tuple(pairing.ignored_detections),
            source_message_id=frame.message_id,
        )
        self.output_port.publish_event(event)
        return event

    def _ensure_calibration(self, frame: DetectionFrame) -> None:
        if self.calibration_store.get(frame.source_id) is not None:
            return
        calibration = self.calibration_port.get_calibration(frame.source_id)
        if calibration is not None:
            self.calibration_store.upsert(calibration)
