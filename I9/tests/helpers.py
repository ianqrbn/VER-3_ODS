"""Helpers compartilhados pelos testes do I9."""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Iterable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.domain.models import (  # noqa: E402
    SCHEMA_VERSION,
    BoundingBox,
    Calibration,
    TrackingFrame,
    utc_now_iso,
)
from src.domain.policy import EquipmentPolicy  # noqa: E402

POLICY_PATH = ROOT / "config" / "policy.json"

# pessoa de referência: 256 x 744, base em y=268, topo em y=1012
PERSON_BOX = BoundingBox(412, 268, 668, 1012)
SECOND_PERSON_BOX = BoundingBox(1100, 300, 1320, 980)


def default_policy() -> EquipmentPolicy:
    return EquipmentPolicy.from_file(POLICY_PATH)


def policy_from(mutation=None) -> EquipmentPolicy:
    """Carrega a política padrão aplicando uma mutação no dicionário."""
    data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if mutation:
        mutation(data)
    return EquipmentPolicy.from_dict(data)


def uncapped_policy() -> EquipmentPolicy:
    """Política sem teto de confiança, para verificar proporções nos testes."""

    def mutation(data: Dict[str, Any]) -> None:
        data.setdefault("confidence", {})["max_confidence"] = 1.0

    return policy_from(mutation)


@contextmanager
def quiet():
    """Silencia a saída do adaptador de console durante os testes."""
    with redirect_stdout(StringIO()):
        yield


def make_bbox(x_min: float, y_min: float, width: float, height: float) -> BoundingBox:
    return BoundingBox(x_min, y_min, x_min + width, y_min + height)


def make_track(
    track_id: int,
    class_name: str,
    bbox: BoundingBox,
    state: str = "confirmed",
) -> Dict[str, Any]:
    return {
        "track_id": track_id,
        "class": class_name,
        "state": state,
        "u_px": bbox.center_x,
        "v_px": bbox.center_y,
        "predicted": state == "predicted",
        "bbox": bbox.as_dict(),
    }


def make_frame(
    tracks: Iterable[Dict[str, Any]],
    camera_id: str = "CAM-01",
    frame: int = 1,
) -> TrackingFrame:
    payload = {
        "camera_id": camera_id,
        "session_id": "sess-teste",
        "captured_at": "2026-09-23T14:05:12.400Z",
        "frame": frame,
        "frame_width": 1920,
        "frame_height": 1080,
        "tracks": list(tracks),
    }
    event = {
        "message_type": "event",
        "schema": "ods.inferencia.rastreio",
        "schema_version": SCHEMA_VERSION,
        "producer": "I2",
        "published_at": utc_now_iso(),
        "payload": payload,
    }
    return TrackingFrame.from_event(event)


def make_calibration(
    camera_id: str = "CAM-01",
    calibration_version: str = "cam-01-v3",
    reprojection_rms_cm: float = 1.8,
    holdout_points: int = 6,
    unit: str = "m",
) -> Calibration:
    return Calibration.from_event(
        {
            "message_type": "event",
            "schema": "ods.inferencia.calibracao",
            "schema_version": SCHEMA_VERSION,
            "producer": "I3",
            "published_at": utc_now_iso(),
            "payload": {
                "camera_id": camera_id,
                "calibration_version": calibration_version,
                "valid_from": "2026-09-23T13:58:00.000Z",
                "homography": [
                    [0.0040, -0.0002, 0.85],
                    [0.0001, -0.0042, 1.15],
                    [-0.0000009, 0.0000021, 1.0],
                ],
                "reference_frame": {
                    "space_id": "teste",
                    "origin": "0,0",
                    "axes": "x,y",
                    "unit": unit,
                },
                "reprojection_rms_cm": reprojection_rms_cm,
                "holdout_points": holdout_points,
            },
        }
    )


def equipment_by_class(event_dict: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
    """Mapeia classe -> item de equipamento da relação indicada."""
    return {item["class"]: item for item in event_dict["payload"]["relations"][index]["equipment"]}


def evidence_of(event_dict: Dict[str, Any], class_name: str, index: int = 0) -> Dict[str, Any]:
    for item in event_dict["payload"]["relations"][index]["equipment"]:
        if item["class"] == class_name:
            return item["evidence"]
    raise AssertionError(f"classe {class_name!r} ausente na relação {index}")
