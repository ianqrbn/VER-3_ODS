"""
Modelos de domínio do componente I9 (verificação geométrica de EPI).

Arquitetura 6c — o I9 processa **um quadro estático** por vez:

* entrada: `ods.i1.detections` (I1) e `ods.i3.calibration` (I3);
* saída: `ods.i9.ppe_compliance` (envelope EV-SINAL), consumido por S2 e A5.

Convenções:

* o I1 publica `bbox` como `[x1, y1, x2, y2]` em pixels, com origem no canto
  **superior** esquerdo (y cresce para baixo);
* internamente o motor geométrico trabalha com origem no canto **inferior**
  esquerdo (`v` alto = cabeça) e `x_max` / `y_max` exclusivos. A conversão é
  feita uma única vez, no parsing da detecção;
* cada detecção carrega o dicionário original em `raw`, e o `detection_id` do
  I1 é repassado sem alteração para que o S2 faça o cruzamento temporal.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Tuple

DETECTIONS_SCHEMA = "ods.i1.detections"
CALIBRATION_SCHEMA = "ods.i3.calibration"
COMPLIANCE_SCHEMA = "ods.i9.ppe_compliance"
SCHEMA_VERSION = "1.0"
PRODUCER = "I9"


class RelationalState(str, Enum):
    """Estados relacionais do motor; no contrato saem como `compliance` (inglês)."""

    CORRETO = "CORRETO"
    INCORRETO = "INCORRETO"
    AUSENTE = "AUSENTE"

    @property
    def compliance(self) -> str:
        """Valor do enum `items[].compliance` de `ods.i9.ppe_compliance`."""
        return _COMPLIANCE[self]


_COMPLIANCE = {
    RelationalState.CORRETO: "CORRECT",
    RelationalState.INCORRETO: "INCORRECT",
    RelationalState.AUSENTE: "ABSENT",
}


def _require(payload: Mapping[str, Any], key: str, context: str) -> Any:
    if key not in payload:
        raise ValueError(f"{context}: campo obrigatório ausente -> {key!r}")
    return payload[key]


def _as_float(value: Any, key: str, context: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{context}: campo inválido -> {key!r}={value!r}")
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


def _optional_int(data: Mapping[str, Any], key: str, context: str) -> Optional[int]:
    value = data.get(key)
    return None if value is None else _as_int(value, key, context)


def _check_schema(event: Mapping[str, Any], expected: str) -> None:
    schema = event.get("schema")
    if schema != expected:
        raise ValueError(f"schema inesperado: esperado {expected!r}, recebido {schema!r}")


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

    def to_image_list(self, image_height: float) -> List[float]:
        """Converte para o formato do I1: `[x1, y1, x2, y2]` com origem superior."""
        return [self.x_min, image_height - self.y_max, self.x_max, image_height - self.y_min]

    @classmethod
    def from_image_list(cls, value: Any, image_height: float, context: str) -> "BoundingBox":
        """Lê `[x1, y1, x2, y2]` (origem superior, formato do I1) para a convenção interna."""
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ValueError(f"{context}: esperado [x1, y1, x2, y2] -> {value!r}")
        x1, y1, x2, y2 = (_as_float(v, "bbox", context) for v in value)
        return cls(x_min=x1, y_min=image_height - y2, x_max=x2, y_max=image_height - y1)


@dataclass(frozen=True)
class Detection:
    """Detecção de um quadro recebida do I1 (pessoa ou equipamento)."""

    detection_id: int
    raw_class: str
    confidence: float
    bbox: BoundingBox
    raw: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def center(self) -> Tuple[float, float]:
        return (self.bbox.center_x, self.bbox.center_y)

    def as_dict(self) -> Dict[str, Any]:
        """Repassa a detecção original sem alteração (garante perda zero de dados)."""
        return dict(self.raw)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], image_height: float, index: int = 0) -> "Detection":
        context = f"detections[{index}]"
        confidence = _as_float(_require(data, "confidence", context), "confidence", context)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"{context}: confidence fora de [0, 1] -> {confidence!r}")

        return cls(
            detection_id=_as_int(_require(data, "detection_id", context), "detection_id", context),
            raw_class=str(_require(data, "class", context)),
            confidence=confidence,
            bbox=BoundingBox.from_image_list(
                _require(data, "bbox", context), image_height, f"{context}.bbox"
            ),
            raw=dict(data),
        )


@dataclass(frozen=True)
class DetectionFrame:
    """Evento `ods.i1.detections` já validado (envelope + payload)."""

    source_id: str
    session_id: str
    captured_at: str
    sequence: Optional[int]
    frame_index: Optional[int]
    image_width: int
    image_height: int
    detections: Tuple[Detection, ...]
    message_id: Optional[str] = None
    artifact_version: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_event(cls, event: Mapping[str, Any]) -> "DetectionFrame":
        """Lê um evento completo do I1 validando o envelope."""
        _check_schema(event, DETECTIONS_SCHEMA)
        context = "event"
        payload = _require(event, "payload", context)

        image_height = _as_int(_require(payload, "image_height", "payload"), "image_height", "payload")
        image_width = _as_int(_require(payload, "image_width", "payload"), "image_width", "payload")
        detections_raw = _require(payload, "detections", "payload")
        if not isinstance(detections_raw, list):
            raise ValueError("payload.detections: esperado lista")

        detections = tuple(
            Detection.from_dict(d, image_height, i) for i, d in enumerate(detections_raw)
        )
        ids = [d.detection_id for d in detections]
        if len(ids) != len(set(ids)):
            raise ValueError("payload.detections: detection_id duplicado no quadro")

        return cls(
            source_id=str(_require(event, "source_id", context)),
            session_id=str(event.get("session_id", "")),
            captured_at=str(event.get("captured_at", "")),
            sequence=_optional_int(event, "sequence", context),
            frame_index=_optional_int(payload, "frame_index", "payload"),
            image_width=image_width,
            image_height=image_height,
            detections=detections,
            message_id=event.get("message_id"),
            artifact_version=event.get("artifact_version"),
            raw=dict(event),
        )


@dataclass(frozen=True)
class Calibration:
    """Calibração de câmera recebida do I3 (`ods.i3.calibration`).

    A homografia imagem -> plano do ambiente é opcional: sem ela o I9 continua
    funcionando, apenas sem o corte métrico de alcance. Parâmetros intrínsecos e
    de distorção são preservados em `raw`.
    """

    source_id: str
    calibration_version: str
    valid_from: str
    homography: Optional[Tuple[Tuple[float, ...], ...]]
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
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        source_id: Optional[str] = None,
        version: Optional[str] = None,
    ) -> "Calibration":
        """Lê o conteúdo do artefato CALIBRATION (Especificação de interfaces 1.0).

        Formato do contrato: `homography_px_to_m` no payload e a versão no
        `artifact_version` do envelope (`version`). O formato anterior
        (`homography` e `calibration_version` no payload) continua aceito.
        """
        context = "calibração"
        matrix = None
        key = "homography_px_to_m" if "homography_px_to_m" in payload else "homography"
        matrix_raw = payload.get(key)
        if matrix_raw is not None:
            if not isinstance(matrix_raw, list) or len(matrix_raw) != 3:
                raise ValueError(f"calibração.{key}: esperado array 3x3")
            matrix = tuple(
                tuple(_as_float(v, key, context) for v in linha)
                for linha in matrix_raw
            )
            if any(len(linha) != 3 for linha in matrix):
                raise ValueError(f"calibração.{key}: esperado array 3x3")

        if source_id is None:
            source_id = payload.get("source_id", payload.get("camera_id"))
        if source_id is None:
            raise ValueError(f"{context}: campo obrigatório ausente -> 'source_id'")

        if version is None:
            version = payload.get("calibration_version")
        if version is None:
            raise ValueError(f"{context}: campo obrigatório ausente -> 'artifact_version'")

        reference = payload.get("reference_frame") or {}
        rms_raw = payload.get("reprojection_rms_cm")

        return cls(
            source_id=str(source_id),
            calibration_version=str(version),
            valid_from=str(payload.get("valid_from", "")),
            homography=matrix,  # type: ignore[arg-type]
            space_id=str(reference.get("space_id", "")),
            unit=str(reference.get("unit", "m")),
            reprojection_rms_cm=(
                None if rms_raw is None else _as_float(rms_raw, "reprojection_rms_cm", context)
            ),
            holdout_points=_optional_int(payload, "holdout_points", context),
            raw=dict(payload),
        )

    @classmethod
    def from_event(cls, event: Mapping[str, Any]) -> "Calibration":
        """Lê um evento completo do I3; câmera e versão vêm do envelope."""
        _check_schema(event, CALIBRATION_SCHEMA)
        return cls.from_payload(
            _require(event, "payload", "event"),
            event.get("source_id"),
            event.get("artifact_version"),
        )


@dataclass(frozen=True)
class EquipmentMatch:
    """EPI associado a uma pessoa (detecção real, nunca sintética)."""

    canonical_class: str
    required: bool
    detection: Detection
    association_score: float
    ground_distance_m: Optional[float] = None


@dataclass(frozen=True)
class PersonRelation:
    """Pessoa e os EPIs que lhe foram associados no quadro."""

    person: Detection
    equipment: Tuple[EquipmentMatch, ...] = ()


@dataclass(frozen=True)
class PairingResult:
    """Resultado da associação geométrica de um quadro."""

    relations: List[PersonRelation]
    unassociated_equipment: List["UnassociatedEquipment"] = field(default_factory=list)
    ignored_detections: List["IgnoredDetection"] = field(default_factory=list)


@dataclass(frozen=True)
class EquipmentEvaluation:
    """Resultado da verificação geométrica de um EPI (detectado ou ausente)."""

    canonical_class: str
    required: bool
    state: RelationalState
    confidence: float
    detection: Optional[Detection]
    uncertain: bool = False
    evidence: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "equipment_item": self.canonical_class,
            "state": self.state.value,
            "confidence": round(self.confidence, 4),
            "uncertain": self.uncertain,
            "detection_id": self.detection.detection_id if self.detection else None,
            "evidence": self.evidence,
        }

    def contract_item(self) -> Dict[str, Any]:
        """Item de `items[]` no contrato; `bbox` só quando o EPI foi localizado."""
        item: Dict[str, Any] = {
            "equipment_item": self.canonical_class,
            "compliance": self.state.compliance,
            "confidence": round(self.confidence, 4),
        }
        if self.detection is not None:
            item["bbox"] = self.detection.raw.get("bbox")
        return item


@dataclass(frozen=True)
class PersonEvaluation:
    person: Detection
    equipment: Tuple[EquipmentEvaluation, ...]
    uncertain_reasons: Tuple[str, ...] = ()

    @property
    def uncertain(self) -> bool:
        return bool(self.uncertain_reasons) or any(e.uncertain for e in self.equipment)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "detection_id": self.person.detection_id,
            "class": self.person.raw_class,
            "confidence": self.person.confidence,
            "bbox": self.person.raw.get("bbox"),
            "uncertain": self.uncertain,
            "uncertain_reasons": list(self.uncertain_reasons),
            "equipment": [e.as_dict() for e in self.equipment],
        }


@dataclass(frozen=True)
class UnassociatedEquipment:
    """EPI detectado no quadro que não pertence a nenhuma pessoa (com segurança)."""

    canonical_class: str
    detection: Detection
    reason: str
    best_association_score: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "equipment_item": self.canonical_class,
            "detection_id": self.detection.detection_id,
            "reason": self.reason,
            "best_association_score": round(self.best_association_score, 4),
        }


@dataclass(frozen=True)
class IgnoredDetection:
    """Detecção recebida mas não utilizada (classe fora da política ou baixa confiança)."""

    detection: Detection
    reason: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "detection_id": self.detection.detection_id,
            "class": self.detection.raw_class,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CalibrationStatus:
    version: Optional[str] = None
    status: str = "missing"
    reason: Optional[str] = None
    # a homografia do I3 foi usada na associação (`calibrated` do contrato)
    applied: bool = False


@dataclass(frozen=True)
class ComplianceEvent:
    """Resultado do I9 para um quadro.

    `messages()` gera o que é publicado em `ods.i9.ppe_compliance`: uma
    mensagem por pessoa detectada (contrato da Especificação de interfaces 1.0).
    O envelope segue o EV-SINAL: `source_id`, `session_id`, `captured_at` e
    `sequence` são os do quadro do I1, para que o S2 case a pessoa com o rastro
    do I2 pela chave do quadro + `detection_id`. `frame_report()` é o relatório
    do quadro inteiro, para diagnóstico; não é publicado.
    """

    source_id: str
    session_id: str
    captured_at: str
    sequence: Optional[int]
    frame_index: Optional[int]
    image_width: Optional[int]
    image_height: Optional[int]
    artifact_version: str
    calibration: CalibrationStatus
    catalog_version: Optional[str] = None
    relations: Tuple[PersonEvaluation, ...] = ()
    unassociated_equipment: Tuple[UnassociatedEquipment, ...] = ()
    ignored_detections: Tuple[IgnoredDetection, ...] = ()
    source_message_id: Optional[str] = None
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    published_at: str = field(default_factory=utc_now_iso)
    # um message_id por mensagem publicada, fixado na criação (idempotência do envio)
    message_ids: Tuple[str, ...] = field(init=False, default=())

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "message_ids", tuple(str(uuid.uuid4()) for _ in self.relations)
        )

    @property
    def uncertain(self) -> bool:
        return any(r.uncertain for r in self.relations)

    def messages(self) -> List[Dict[str, Any]]:
        """Mensagens `ods.i9.ppe_compliance`, uma por pessoa; vazia sem pessoas."""
        return [
            {
                "message_type": "event",
                "message_id": message_id,
                "schema": COMPLIANCE_SCHEMA,
                "schema_version": SCHEMA_VERSION,
                "producer": PRODUCER,
                "published_at": self.published_at,
                "captured_at": self.captured_at,
                "source_id": self.source_id,
                "session_id": self.session_id,
                "sequence": self.sequence,
                "artifact_version": self.artifact_version,
                "payload": {
                    "frame_index": self.frame_index,
                    "detection_id": relation.person.detection_id,
                    "bbox": relation.person.raw.get("bbox"),
                    "calibrated": self.calibration.applied,
                    "catalog_version": self.catalog_version,
                    "items": [e.contract_item() for e in relation.equipment],
                    "uncertain": relation.uncertain,
                },
            }
            for relation, message_id in zip(self.relations, self.message_ids)
        ]

    def frame_report(self) -> Dict[str, Any]:
        """Relatório do quadro inteiro (diagnóstico local, fora do contrato)."""
        return {
            "captured_at": self.captured_at,
            "source_id": self.source_id,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "artifact_version": self.artifact_version,
            "payload": {
                "frame_index": self.frame_index,
                "image_width": self.image_width,
                "image_height": self.image_height,
                "source_message_id": self.source_message_id,
                "catalog_version": self.catalog_version,
                "calibration_version": self.calibration.version,
                "calibration_status": self.calibration.status,
                "uncertain": self.uncertain,
                "persons": [r.as_dict() for r in self.relations],
                "unassociated_equipment": [u.as_dict() for u in self.unassociated_equipment],
                "ignored_detections": [i.as_dict() for i in self.ignored_detections],
            },
        }

    def detection_ids_covered(self) -> set:
        ids = set()
        for relation in self.relations:
            ids.add(relation.person.detection_id)
            for equipment in relation.equipment:
                if equipment.detection:
                    ids.add(equipment.detection.detection_id)
        for item in self.unassociated_equipment:
            ids.add(item.detection.detection_id)
        for item in self.ignored_detections:
            ids.add(item.detection.detection_id)
        return ids


@dataclass(frozen=True)
class AnnotatedTrack:
    """Objeto de ground truth do dataset anotado (uma linha do CSV / anotação COCO)."""

    track_id: int
    raw_class: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    relational_state: Optional[RelationalState] = None

    @property
    def bbox(self) -> BoundingBox:
        return BoundingBox(
            x_min=self.x_min,
            y_min=self.y_min,
            x_max=self.x_max,
            y_max=self.y_max,
        )


@dataclass(frozen=True)
class AnnotatedFrame:
    """Frame anotado com ground truth para calibração."""

    camera_id: str
    frame: int
    tracks: Tuple[AnnotatedTrack, ...]
    homography: Optional[Tuple[Tuple[float, ...], ...]] = None

    def ground_truth_for(self, person_track_id: int, canonical_class: str) -> Optional[RelationalState]:
        """Ground truth de um par pessoa×EPI.

        Retorna None quando o par não existe no ground truth (ex.: EPI ausente
        não foi anotado explicitamente).
        """
        for track in self.tracks:
            if track.track_id == person_track_id:
                continue
            if track.relational_state is None:
                continue
            # Verifica se o track é da classe canônica esperada
            # (a política mapeia raw_class -> canonical)
            # Aqui comparamos pelo raw_class diretamente
            if track.raw_class.lower() == canonical_class.lower():
                return track.relational_state
        return None

    def to_detection_frame(self) -> DetectionFrame:
        """Converte para DetectionFrame (para rodar o pipeline).

        As anotações já estão na convenção interna (origem inferior); o
        `track_id` anotado vira o `detection_id` e a confiança é 1.0.
        """
        image_height = 1080
        detections = tuple(
            Detection(
                detection_id=t.track_id,
                raw_class=t.raw_class,
                confidence=1.0,
                bbox=t.bbox,
                raw={
                    "detection_id": t.track_id,
                    "class": t.raw_class,
                    "confidence": 1.0,
                    "bbox": t.bbox.to_image_list(image_height),
                },
            )
            for t in self.tracks
        )
        return DetectionFrame(
            source_id=self.camera_id,
            session_id=f"calib-{self.frame:06d}",
            captured_at=utc_now_iso(),
            sequence=self.frame,
            frame_index=self.frame,
            image_width=1920,
            image_height=image_height,
            detections=detections,
        )
