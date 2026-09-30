"""
Modelos de domínio do componente I9 (verificação geométrica de EPI).

Convenções do contrato de rastreio (I2):

* `u_px` / `v_px` e `bbox` estão no mesmo espaço de pixels;
* a origem da imagem é o canto **inferior esquerdo** (mesmo sistema do OpenCV);
* `x_max` e `y_max` são **exclusivos**;
* cada track carrega seu payload original em `raw`, que é repassado sem
  alteração no evento de saída.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Tuple

TRACKING_SCHEMA = "ods.inferencia.rastreio"
CALIBRATION_SCHEMA = "ods.inferencia.calibracao"
RELATIONAL_SCHEMA = "ods.inferencia.relacional"
SCHEMA_VERSION = "1.0"
PRODUCER = "I9"


class RelationalState(str, Enum):
    """Estados relacionais previstos no contrato de saída."""

    CORRETO = "CORRETO"
    INCORRETO = "INCORRETO"
    AUSENTE = "AUSENTE"


class TrackState(str, Enum):
    """Estados de rastreio informados pelo I2."""

    CONFIRMED = "confirmed"
    PREDICTED = "predicted"
    LOST = "lost"


def _require(payload: Mapping[str, Any], key: str, context: str) -> Any:
    if key not in payload:
        raise ValueError(f"{context}: campo obrigatório ausente -> {key!r}")
    return payload[key]


def _as_float(value: Any, key: str, context: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context}: campo inválido -> {key!r}={value!r}") from exc


def _as_int(value: Any, key: str, context: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{context}: campo inválido -> {key!r}={value!r}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context}: campo inválido -> {key!r}={value!r}") from exc


def utc_now_iso() -> str:
    """Timestamp UTC no formato ISO-8601 com milissegundos (formato do contrato)."""
    agora = datetime.now(timezone.utc)
    return agora.strftime("%Y-%m-%dT%H:%M:%S.") + f"{agora.microsecond // 1000:03d}Z"


@dataclass(frozen=True)
class BoundingBox:
    """Retângulo em pixels com origem inferior esquerda e máximos exclusivos."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self) -> None:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError(
                "bbox inválida: exige x_max > x_min e y_max > y_min -> "
                f"({self.x_min}, {self.y_min}, {self.x_max}, {self.y_max})"
            )

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def center_x(self) -> float:
        return (self.x_min + self.x_max) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y_min + self.y_max) / 2.0

    @property
    def area(self) -> float:
        return self.width * self.height

    def contains(self, x: float, y: float) -> bool:
        """Teste de contenção com máximo exclusivo."""
        return self.x_min <= x < self.x_max and self.y_min <= y < self.y_max

    def intersection_area(self, other: "BoundingBox") -> float:
        dx = min(self.x_max, other.x_max) - max(self.x_min, other.x_min)
        dy = min(self.y_max, other.y_max) - max(self.y_min, other.y_min)
        if dx <= 0 or dy <= 0:
            return 0.0
        return dx * dy

    def iou(self, other: "BoundingBox") -> float:
        inter = self.intersection_area(other)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def containment(self, other: "BoundingBox") -> float:
        """Fração da área de `other` contida nesta caixa."""
        return self.intersection_area(other) / other.area if other.area > 0 else 0.0

    def expanded(self, ratio_x: float, ratio_y: float) -> "BoundingBox":
        dx = self.width * ratio_x
        dy = self.height * ratio_y
        return BoundingBox(self.x_min - dx, self.y_min - dy, self.x_max + dx, self.y_max + dy)

    def as_dict(self) -> Dict[str, float]:
        return {
            "x_min": self.x_min,
            "y_min": self.y_min,
            "x_max": self.x_max,
            "y_max": self.y_max,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], context: str) -> "BoundingBox":
        return cls(
            x_min=_as_float(_require(data, "x_min", context), "x_min", context),
            y_min=_as_float(_require(data, "y_min", context), "y_min", context),
            x_max=_as_float(_require(data, "x_max", context), "x_max", context),
            y_max=_as_float(_require(data, "y_max", context), "y_max", context),
        )


@dataclass(frozen=True)
class Track:
    """Track de rastreio recebida do I2 (pessoa ou equipamento)."""

    track_id: int
    raw_class: str
    state: Optional[TrackState]
    u_px: float
    v_px: float
    predicted: bool
    bbox: BoundingBox
    raw: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def center(self) -> Tuple[float, float]:
        return (self.bbox.center_x, self.bbox.center_y)

    def as_dict(self) -> Dict[str, Any]:
        """Repassa o track original sem alteração (garante perda zero de dados)."""
        return dict(self.raw)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], index: int = 0) -> "Track":
        context = f"tracks[{index}]"
        state_raw = data.get("state")
        try:
            state = TrackState(state_raw) if state_raw is not None else None
        except ValueError:
            state = None  # estado desconhecido: tratado de forma conservadora

        return cls(
            track_id=_as_int(_require(data, "track_id", context), "track_id", context),
            raw_class=str(_require(data, "class", context)),
            state=state,
            u_px=_as_float(_require(data, "u_px", context), "u_px", context),
            v_px=_as_float(_require(data, "v_px", context), "v_px", context),
            predicted=bool(data.get("predicted", state is TrackState.PREDICTED)),
            bbox=BoundingBox.from_dict(_require(data, "bbox", context), f"{context}.bbox"),
            raw=dict(data),
        )


@dataclass(frozen=True)
class TrackingFrame:
    """Payload do evento `ods.inferencia.rastreio` já validado."""

    camera_id: str
    session_id: str
    captured_at: str
    frame: Optional[int]
    frame_width: Optional[int]
    frame_height: Optional[int]
    tracks: Tuple[Track, ...]
    raw: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def of_state(self, state: TrackState) -> List[Track]:
        return [t for t in self.tracks if t.state is state]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TrackingFrame":
        context = "payload"
        tracks_raw = _require(payload, "tracks", context)
        if not isinstance(tracks_raw, list):
            raise ValueError("payload.tracks: esperado lista")

        frame_raw = payload.get("frame")
        frame = None if frame_raw is None else _as_int(frame_raw, "frame", context)
        width_raw = payload.get("frame_width")
        height_raw = payload.get("frame_height")

        return cls(
            camera_id=str(_require(payload, "camera_id", context)),
            session_id=str(payload.get("session_id", "")),
            captured_at=str(payload.get("captured_at", "")),
            frame=frame,
            frame_width=None if width_raw is None else _as_int(width_raw, "frame_width", context),
            frame_height=None if height_raw is None else _as_int(height_raw, "frame_height", context),
            tracks=tuple(Track.from_dict(t, i) for i, t in enumerate(tracks_raw)),
            raw=dict(payload),
        )

    @classmethod
    def from_event(cls, event: Mapping[str, Any]) -> "TrackingFrame":
        """Lê um evento completo do I2 validando o envelope."""
        schema = event.get("schema")
        if schema != TRACKING_SCHEMA:
            raise ValueError(f"schema inesperado: esperado {TRACKING_SCHEMA!r}, recebido {schema!r}")
        return cls.from_payload(_require(event, "payload", "event"))


@dataclass(frozen=True)
class Calibration:
    """Calibração de câmera recebida do I3 (homografia imagem -> plano do ambiente)."""

    camera_id: str
    calibration_version: str
    valid_from: str
    homography: Tuple[Tuple[float, ...], ...]
    space_id: str
    unit: str
    reprojection_rms_cm: Optional[float]
    holdout_points: Optional[int]
    raw: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.raw)

    @property
    def meters_per_unit(self) -> float:
        """Fator para converter distâncias do referencial para metros."""
        factor = self.unit.strip().lower()
        if factor in ("m", "meter", "meters", "metros", "metro"):
            return 1.0
        if factor in ("cm", "centimeter", "centimeters", "centimetro", "centimetros"):
            return 0.01
        if factor in ("mm", "milimeter", "milimetros"):
            return 0.001
        return 1.0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "Calibration":
        context = "calibração"
        matrix_raw = _require(payload, "homography", context)
        if not isinstance(matrix_raw, list) or len(matrix_raw) != 3:
            raise ValueError("calibração.homography: esperado array 3x3")
        matrix = tuple(
            tuple(_as_float(v, "homography", context) for v in linha)
            for linha in matrix_raw
        )
        if any(len(linha) != 3 for linha in matrix):
            raise ValueError("calibração.homography: esperado array 3x3")

        reference = payload.get("reference_frame") or {}
        rms_raw = payload.get("reprojection_rms_cm")
        holdout_raw = payload.get("holdout_points")

        return cls(
            camera_id=str(_require(payload, "camera_id", context)),
            calibration_version=str(_require(payload, "calibration_version", context)),
            valid_from=str(payload.get("valid_from", "")),
            homography=matrix,  # type: ignore[arg-type]
            space_id=str(reference.get("space_id", "")),
            unit=str(reference.get("unit", "m")),
            reprojection_rms_cm=(
                None if rms_raw is None else _as_float(rms_raw, "reprojection_rms_cm", context)
            ),
            holdout_points=None if holdout_raw is None else _as_int(holdout_raw, "holdout_points", context),
            raw=dict(payload),
        )

    @classmethod
    def from_event(cls, event: Mapping[str, Any]) -> "Calibration":
        schema = event.get("schema")
        if schema != CALIBRATION_SCHEMA:
            raise ValueError(f"schema inesperado: esperado {CALIBRATION_SCHEMA!r}, recebido {schema!r}")
        return cls.from_payload(_require(event, "payload", "event"))


@dataclass(frozen=True)
class EquipmentMatch:
    """EPI associado a uma pessoa (track detectada, nunca sintética)."""

    canonical_class: str
    required: bool
    track: Track
    association_score: float
    ground_distance_m: Optional[float] = None


@dataclass(frozen=True)
class PersonRelation:
    """Pessoa e os EPIs que lhe foram associados no frame."""

    person: Track
    equipment: Tuple[EquipmentMatch, ...] = ()


@dataclass(frozen=True)
class PairingResult:
    """Resultado da associação geométrica de um frame."""

    relations: List[PersonRelation]
    unassociated_equipment: List["UnassociatedEquipment"] = field(default_factory=list)
    ignored_tracks: List["IgnoredTrack"] = field(default_factory=list)


@dataclass(frozen=True)
class EquipmentEvaluation:
    """Resultado da verificação geométrica de um EPI (detectado ou ausente)."""

    canonical_class: str
    required: bool
    state: RelationalState
    confidence_pct: float
    track: Optional[Track]
    evidence: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "class": self.canonical_class,
            "required": self.required,
            "relational_state": self.state.value,
            "confidence_pct": round(self.confidence_pct, 2),
            "detection": self.track.as_dict() if self.track else None,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class PersonEvaluation:
    person: Track
    equipment: Tuple[EquipmentEvaluation, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "person": self.person.as_dict(),
            "equipment": [e.as_dict() for e in self.equipment],
        }


@dataclass(frozen=True)
class UnassociatedEquipment:
    """EPI detectado no frame que não pertence a nenhuma pessoa (com segurança)."""

    canonical_class: str
    track: Track
    reason: str
    best_association_score_pct: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "class": self.canonical_class,
            "track": self.track.as_dict(),
            "reason": self.reason,
            "best_association_score_pct": round(self.best_association_score_pct, 2),
        }


@dataclass(frozen=True)
class IgnoredTrack:
    """Track recebida mas não utilizada na verificação (ex.: estado `lost`)."""

    track: Track
    reason: str

    def as_dict(self) -> Dict[str, Any]:
        return {"track": self.track.as_dict(), "reason": self.reason}


@dataclass(frozen=True)
class CalibrationStatus:
    version: Optional[str] = None
    status: str = "missing"
    reason: Optional[str] = None


@dataclass(frozen=True)
class RelationalEvent:
    """Evento de saída do I9 (`ods.inferencia.relacional`), um por quadro."""

    camera_id: str
    session_id: str
    frame: Optional[int]
    captured_at: str
    frame_width: Optional[int]
    frame_height: Optional[int]
    calibration: CalibrationStatus
    policy_id: str
    policy_version: str
    relations: Tuple[PersonEvaluation, ...] = ()
    unassociated_equipment: Tuple[UnassociatedEquipment, ...] = ()
    ignored_tracks: Tuple[IgnoredTrack, ...] = ()
    published_at: str = field(default_factory=utc_now_iso)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "message_type": "event",
            "schema": RELATIONAL_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "producer": PRODUCER,
            "published_at": self.published_at,
            "payload": {
                "camera_id": self.camera_id,
                "session_id": self.session_id,
                "frame": self.frame,
                "captured_at": self.captured_at,
                "frame_width": self.frame_width,
                "frame_height": self.frame_height,
                "calibration_version": self.calibration.version,
                "calibration_status": self.calibration.status,
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "relations": [r.as_dict() for r in self.relations],
                "unassociated_equipment": [u.as_dict() for u in self.unassociated_equipment],
                "ignored_tracks": [i.as_dict() for i in self.ignored_tracks],
            },
        }

    def track_ids_covered(self) -> set:
        ids = set()
        for relation in self.relations:
            ids.add(relation.person.track_id)
            for equipment in relation.equipment:
                if equipment.track:
                    ids.add(equipment.track.track_id)
        for item in self.unassociated_equipment:
            ids.add(item.track.track_id)
        for item in self.ignored_tracks:
            ids.add(item.track.track_id)
        return ids
