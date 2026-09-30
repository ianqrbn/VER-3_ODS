"""
Orquestração do componente I9 por quadro.

O pipeline é deliberadamente burro: busca um evento de rastreio, garante a
calibração da câmera, executa a associação geométrica, infere os estados
relacionais e publica o evento resultante. Não há estado acumulado entre
quadros — as regras temporais são responsabilidade do I2.
"""

from __future__ import annotations

from typing import Optional

from src.core.calibration import CalibrationStore
from src.core.inference import RelationInferenceModule
from src.core.pairing import PairingModule
from src.domain.models import RelationalEvent, TrackingFrame
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

        if pairing_module.calibration_store is None:
            raise ValueError("o PairingModule precisa de um CalibrationStore")

    @property
    def calibration_store(self) -> CalibrationStore:
        return self.pairing_module.calibration_store

    def run_once(self) -> Optional[RelationalEvent]:
        """Processa o próximo quadro. Retorna None quando não há mais dados."""
        frame = self.ingestion_port.get_next_event()
        if frame is None:
            return None
        return self.process(frame)

    def process(self, frame: TrackingFrame) -> RelationalEvent:
        self._ensure_calibration(frame)

        pairing = self.pairing_module.pair(frame)
        evaluations = self.inference_module.infer(pairing)

        event = RelationalEvent(
            camera_id=frame.camera_id,
            session_id=frame.session_id,
            frame=frame.frame,
            captured_at=frame.captured_at,
            frame_width=frame.frame_width,
            frame_height=frame.frame_height,
            calibration=self.calibration_store.status(frame.camera_id),
            policy_id=self.policy.policy_id,
            policy_version=self.policy.version,
            relations=tuple(evaluations),
            unassociated_equipment=tuple(pairing.unassociated_equipment),
            ignored_tracks=tuple(pairing.ignored_tracks),
        )
        self.output_port.publish_event(event)
        return event

    def _ensure_calibration(self, frame: TrackingFrame) -> None:
        if self.calibration_store.get(frame.camera_id) is not None:
            return
        calibration = self.calibration_port.get_calibration(frame.camera_id)
        if calibration is not None:
            self.calibration_store.upsert(calibration)
