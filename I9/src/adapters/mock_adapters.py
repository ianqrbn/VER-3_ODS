"""
Adaptadores de simulação (mocks) das pontas do I9.

Servem para exercitar o fluxo completo sem transporte: o `MockIngestionAdapter`
produz eventos `ods.inferencia.rastreio` idênticos ao que o I2 publica, e o
`MockCalibrationAdapter` produz um evento `ods.inferencia.calibracao` como o I3.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.domain.models import (
    CALIBRATION_SCHEMA,
    SCHEMA_VERSION,
    Calibration,
    RelationalEvent,
    TrackingFrame,
    utc_now_iso,
)

FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080


def _box(x_min: float, y_min: float, width: float, height: float) -> Dict[str, float]:
    """Bbox com origem inferior esquerda e máximos exclusivos."""
    return {
        "x_min": round(float(x_min), 1),
        "y_min": round(float(y_min), 1),
        "x_max": round(float(x_min + width), 1),
        "y_max": round(float(y_min + height), 1),
    }


def _track(
    track_id: int,
    class_name: str,
    x_min: float,
    y_min: float,
    width: float,
    height: float,
    state: str = "confirmed",
) -> Dict[str, Any]:
    bbox = _box(x_min, y_min, width, height)
    return {
        "track_id": track_id,
        "class": class_name,
        "state": state,
        "u_px": round((bbox["x_min"] + bbox["x_max"]) / 2.0, 1),
        "v_px": round((bbox["y_min"] + bbox["y_max"]) / 2.0, 1),
        "predicted": state == "predicted",
        "bbox": bbox,
    }


def _event(payload: Dict[str, Any], schema: str, producer: str) -> Dict[str, Any]:
    return {
        "message_type": "event",
        "schema": schema,
        "schema_version": SCHEMA_VERSION,
        "producer": producer,
        "published_at": utc_now_iso(),
        "payload": payload,
    }


class MockIngestionAdapter:
    """Fonte de quadros simulados, um por iteração."""

    def __init__(self, max_frames: int = 3, camera_id: str = "CAM-01"):
        self.max_frames = max_frames
        self.camera_id = camera_id
        self.current_frame = 0
        self.frames: List[TrackingFrame] = []

    def get_next_event(self) -> Optional[TrackingFrame]:
        if self.current_frame >= self.max_frames:
            return None
        self.current_frame += 1

        payload = {
            "camera_id": self.camera_id,
            "session_id": f"sess-mock-{self.current_frame:04d}",
            "captured_at": utc_now_iso(),
            "frame": 1000 + self.current_frame,
            "frame_width": FRAME_WIDTH,
            "frame_height": FRAME_HEIGHT,
            "tracks": self._build_tracks(self.current_frame),
        }
        frame = TrackingFrame.from_event(_event(payload, "ods.inferencia.rastreio", "I2"))
        self.frames.append(frame)
        return frame

    def _build_tracks(self, index: int) -> List[Dict[str, Any]]:
        # Pessoa 1: sempre presente; colete propositalmente deslocado para o quadril.
        pessoa_1 = _track(42, "pessoa", 412, 268, 256, 744)
        capacete_1 = _track(101, "capacete", 468, 884, 144, 150)
        colete_1 = _track(102, "colete", 430, 346, 220, 200)

        # Pessoa 2: capacete previsto (predicted) no primeiro quadro, confirmado depois.
        # Pessoa 2 não tem colete no primeiro quadro -> AUSENTE.
        pessoa_2 = _track(57, "pessoa", 1100, 300, 220, 680)
        capacete_2 = _track(201, "capacete", 1147, 864, 134, 150, "predicted")

        # EPI detectado longe de qualquer pessoa: deve sair em unassociated_equipment.
        capacete_perdido = _track(301, "capacete", 1600, 200, 100, 120)

        if index == 1:
            return [pessoa_1, capacete_1, colete_1, pessoa_2, capacete_2, capacete_perdido]

        if index == 2:
            # colete 2 surge e o capacete da pessoa 2 é confirmado
            colete_2 = _track(202, "colete", 1130, 580, 160, 200)
            capacete_2_confirmado = _track(201, "capacete", 1147, 864, 134, 150, "confirmed")
            return [
                pessoa_1,
                capacete_1,
                colete_1,
                pessoa_2,
                capacete_2_confirmado,
                colete_2,
                capacete_perdido,
            ]

        # quadro 3: colete 2 perdido pelo tracker
        colete_2_lost = _track(202, "colete", 1130, 580, 160, 200, "lost")
        return [
            pessoa_1,
            capacete_1,
            colete_1,
            pessoa_2,
            capacete_2,
            colete_2_lost,
            capacete_perdido,
        ]


class MockCalibrationAdapter:
    """Calibração sintética (homografia ilustrativa) para a câmera do mock."""

    def __init__(
        self,
        camera_id: str = "CAM-01",
        calibration_version: str = "cam-01-v3",
        reprojection_rms_cm: float = 1.8,
        holdout_points: int = 6,
    ):
        self.camera_id = camera_id
        self.calibration_version = calibration_version
        self.reprojection_rms_cm = reprojection_rms_cm
        self.holdout_points = holdout_points

    def get_calibration(self, camera_id: str) -> Optional[Calibration]:
        if camera_id != self.camera_id:
            return None
        return Calibration.from_event(
            _event(
                {
                    "camera_id": self.camera_id,
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
            )
        )


class MockConsoleOutputAdapter:
    """Publica o evento no console, em formato legível ou como JSON bruto."""

    def __init__(self, as_json: bool = False):
        self.as_json = as_json
        self.events: List[RelationalEvent] = []

    def publish_event(self, event: RelationalEvent) -> None:
        self.events.append(event)
        if self.as_json:
            print(json.dumps(event.as_dict(), ensure_ascii=False, indent=2))
            return

        payload = event.as_dict()["payload"]
        print(f"\n=== {payload['camera_id']} | frame {payload['frame']} | {payload['captured_at']} ===")
        print(
            f"calibração: {payload['calibration_status']} ({payload['calibration_version']}) "
            f"| política: {payload['policy_id']}@{payload['policy_version']}"
        )

        for relation in payload["relations"]:
            person = relation["person"]
            print(f"  Pessoa track_id={person['track_id']} ({person['state']})")
            for item in relation["equipment"]:
                detection = item["detection"]
                origin = f"track_id={detection['track_id']}" if detection else "sem detecção"
                print(
                    f"    - {item['class']:<10} {item['relational_state']:<10} "
                    f"confiança {item['confidence_pct']:>6.2f}%  {origin}"
                )

        for item in payload["unassociated_equipment"]:
            print(
                f"  [não relacionado] {item['class']} track_id={item['track']['track_id']} "
                f"({item['reason']}, melhor score {item['best_association_score_pct']:.2f}%)"
            )

        for item in payload["ignored_tracks"]:
            print(
                f"  [descartado] track_id={item['track']['track_id']} "
                f"({item['track']['class']}): {item['reason']}"
            )
