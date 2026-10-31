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
    DetectionFrame,
    utc_now_iso,
)
from src.domain.policy import EquipmentPolicy  # noqa: E402

POLICY_PATH = ROOT / "config" / "policy.json"

# As caixas dos testes são escritas na convenção interna (origem inferior) e
# convertidas para o formato do I1 ([x1, y1, x2, y2], origem superior) em
# `make_detection`, exercitando a conversão do parsing.
IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1080

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


def make_detection(
    detection_id: int,
    class_name: str,
    bbox: BoundingBox,
    confidence: float = 1.0,
) -> Dict[str, Any]:
    return {
        "detection_id": detection_id,
        "class": class_name,
        "confidence": confidence,
        "bbox": bbox.to_image_list(IMAGE_HEIGHT),
    }


def make_event(
    detections: Iterable[Dict[str, Any]],
    source_id: str = "CAM-01",
    frame_index: int = 1,
) -> Dict[str, Any]:
    return {
        "message_type": "event",
        "message_id": "a8f5f167-99b4-4d2b-8b1e-6c9a2e4f1d3b",
        "schema": "ods.i1.detections",
        "schema_version": SCHEMA_VERSION,
        "producer": "I1",
        "published_at": utc_now_iso(),
        "captured_at": "2026-09-23T14:05:12.400Z",
        "source_id": source_id,
        "session_id": "sess-teste",
        "sequence": frame_index,
        "artifact_version": "app-epi-1.0.0",
        "payload": {
            "frame_index": frame_index,
            "image_width": IMAGE_WIDTH,
            "image_height": IMAGE_HEIGHT,
            "detections": list(detections),
        },
    }


def make_frame(
    detections: Iterable[Dict[str, Any]],
    source_id: str = "CAM-01",
    frame_index: int = 1,
) -> DetectionFrame:
    return DetectionFrame.from_event(make_event(detections, source_id, frame_index))


def make_calibration(
    source_id: str = "CAM-01",
    calibration_version: str = "cam-01-v3",
    reprojection_rms_cm: float = 1.8,
    holdout_points: int = 6,
    unit: str = "m",
) -> Calibration:
    return Calibration.from_event(
        {
            "message_type": "event",
            "schema": "ods.i3.calibration",
            "schema_version": SCHEMA_VERSION,
            "producer": "I3",
            "published_at": utc_now_iso(),
            "source_id": source_id,
            "payload": {
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
    """Mapeia classe -> item de equipamento da pessoa indicada."""
    return {
        item["equipment_item"]: item
        for item in event_dict["payload"]["persons"][index]["equipment"]
    }


def evidence_of(event_dict: Dict[str, Any], class_name: str, index: int = 0) -> Dict[str, Any]:
    for item in event_dict["payload"]["persons"][index]["equipment"]:
        if item["equipment_item"] == class_name:
            return item["evidence"]
    raise AssertionError(f"classe {class_name!r} ausente na relação {index}")
