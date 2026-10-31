"""
Adaptadores de simulação (mocks) das pontas do I9.

Servem para exercitar o fluxo completo sem transporte: o `MockIngestionAdapter`
produz eventos `ods.i1.detections` idênticos ao que o I1 publica, e o
`MockCalibrationAdapter` produz um evento `ods.i3.calibration` como o I3.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from src.domain.models import (
    CALIBRATION_SCHEMA,
    DETECTIONS_SCHEMA,
    SCHEMA_VERSION,
    Calibration,
    ComplianceEvent,
    DetectionFrame,
    utc_now_iso,
)

IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1080


def _detection(
    detection_id: int,
    class_name: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    confidence: float = 0.93,
) -> Dict[str, Any]:
    """Detecção no formato do I1: bbox `[x1, y1, x2, y2]` com origem superior esquerda."""
    return {
        "detection_id": detection_id,
        "class": class_name,
        "confidence": confidence,
        "bbox": [x1, y1, x2, y2],
    }


def _event(payload: Dict[str, Any], schema: str, producer: str, **envelope: Any) -> Dict[str, Any]:
    return {
        "message_type": "event",
        "message_id": str(uuid.uuid4()),
        "schema": schema,
        "schema_version": SCHEMA_VERSION,
        "producer": producer,
        "published_at": utc_now_iso(),
        **envelope,
        "payload": payload,
    }


class MockIngestionAdapter:
    """Fonte de quadros simulados do I1, um por iteração."""

    def __init__(self, max_frames: int = 3, source_id: str = "cam0"):
        self.max_frames = max_frames
        self.source_id = source_id
        self.session_id = str(uuid.uuid4())
        self.current_frame = 0
        self.frames: List[DetectionFrame] = []

    def get_next_event(self) -> Optional[DetectionFrame]:
        if self.current_frame >= self.max_frames:
            return None
        self.current_frame += 1

        frame_index = 1000 + self.current_frame
        payload = {
            "frame_index": frame_index,
            "image_width": IMAGE_WIDTH,
            "image_height": IMAGE_HEIGHT,
            "detections": self._build_detections(self.current_frame),
        }
        event = _event(
            payload,
            DETECTIONS_SCHEMA,
            "I1",
            captured_at=utc_now_iso(),
            source_id=self.source_id,
            session_id=self.session_id,
            sequence=frame_index,
            artifact_version="app-epi-1.0.0",
        )
        frame = DetectionFrame.from_event(event)
        self.frames.append(frame)
        return frame

    def _build_detections(self, index: int) -> List[Dict[str, Any]]:
        # Pessoa 0: sempre presente; colete propositalmente deslocado para o quadril.
        pessoa_0 = _detection(0, "pessoa", 412, 68, 668, 812, 0.94)
        capacete_0 = _detection(1, "capacete", 468, 46, 612, 196, 0.96)
        colete_0 = _detection(2, "colete", 430, 534, 650, 734, 0.93)

        # Pessoa 3: capacete com detecção fraca no primeiro quadro, firme depois.
        # Pessoa 3 não tem colete no primeiro quadro -> AUSENTE.
        pessoa_3 = _detection(3, "pessoa", 1100, 100, 1320, 780, 0.91)
        capacete_3_fraco = _detection(4, "capacete", 1147, 66, 1281, 216, 0.45)
        capacete_3 = _detection(4, "capacete", 1147, 66, 1281, 216, 0.92)

        # EPI detectado longe de qualquer pessoa: deve sair em unassociated_equipment.
        capacete_solto = _detection(6, "capacete", 1600, 760, 1700, 880, 0.88)

        if index == 1:
            return [pessoa_0, capacete_0, colete_0, pessoa_3, capacete_3_fraco, capacete_solto]

        colete_3 = _detection(5, "colete", 1130, 300, 1290, 500, 0.90)
        if index == 2:
            return [pessoa_0, capacete_0, colete_0, pessoa_3, capacete_3, colete_3, capacete_solto]

        # quadro 3: colete da pessoa 3 com confiança abaixo do mínimo -> descartado
        colete_3_ruido = _detection(5, "colete", 1130, 300, 1290, 500, 0.12)
        return [pessoa_0, capacete_0, colete_0, pessoa_3, capacete_3, colete_3_ruido, capacete_solto]


class MockCalibrationAdapter:
    """Calibração sintética (homografia ilustrativa) para a câmera do mock."""

    def __init__(
        self,
        source_id: str = "cam0",
        calibration_version: str = "cam0-v3",
        reprojection_rms_cm: float = 1.8,
        holdout_points: int = 6,
    ):
        self.source_id = source_id
        self.calibration_version = calibration_version
        self.reprojection_rms_cm = reprojection_rms_cm
        self.holdout_points = holdout_points

    def get_calibration(self, source_id: str) -> Optional[Calibration]:
        if source_id != self.source_id:
            return None
        return Calibration.from_event(
            _event(
                {
                    "calibration_version": self.calibration_version,
                    "valid_from": "2026-09-23T13:58:00.000Z",
                    "homography": [
                        [0.0040, -0.0002, 0.85],
                        [0.0001, -0.0042, 1.15],
                        [-0.0000009, 0.0000021, 1.0],
                    ],
                    "reference_frame": {
                        "space_id": "mock-area",
                        "origin": "0,0",
                        "axes": "x_direita,y_frente",
                        "unit": "m",
                    },
                    "reprojection_rms_cm": self.reprojection_rms_cm,
                    "holdout_points": self.holdout_points,
                },
                CALIBRATION_SCHEMA,
                "I3",
                source_id=self.source_id,
            )
        )


class MockConsoleOutputAdapter:
    """Publica o evento no console, em formato legível ou como JSON bruto."""

    def __init__(self, as_json: bool = False):
        self.as_json = as_json
        self.events: List[ComplianceEvent] = []

    def publish_event(self, event: ComplianceEvent) -> None:
        self.events.append(event)
        body = event.as_dict()
        if self.as_json:
            print(json.dumps(body, ensure_ascii=False, indent=2))
            return

        payload = body["payload"]
        print(
            f"\n=== {body['source_id']} | frame {payload['frame_index']} "
            f"| seq {body['sequence']} | {body['captured_at']} ==="
        )
        print(
            f"calibração: {payload['calibration_status']} ({payload['calibration_version']}) "
            f"| modelo: {body['artifact_version']} | uncertain: {payload['uncertain']}"
        )

        for person in payload["persons"]:
            flags = f" [incerto: {', '.join(person['uncertain_reasons'])}]" if person["uncertain_reasons"] else ""
            print(f"  Pessoa detection_id={person['detection_id']} ({person['confidence']:.2f}){flags}")
            for item in person["equipment"]:
                origin = (
                    f"detection_id={item['detection_id']}"
                    if item["detection_id"] is not None
                    else "sem detecção"
                )
                incerto = "  (uncertain)" if item["uncertain"] else ""
                print(
                    f"    - {item['equipment_item']:<10} {item['state']:<10} "
                    f"confiança {item['confidence']:.4f}  {origin}{incerto}"
                )

        for item in payload["unassociated_equipment"]:
            print(
                f"  [não relacionado] {item['equipment_item']} detection_id={item['detection_id']} "
                f"({item['reason']}, melhor score {item['best_association_score']:.4f})"
            )

        for item in payload["ignored_detections"]:
            print(
                f"  [descartado] detection_id={item['detection_id']} "
                f"({item['class']}): {item['reason']}"
            )
