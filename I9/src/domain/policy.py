"""
Política de verificação geométrica: define, por aplicação, quais classes de EPI
existem, quais são obrigatórias e onde cada uma deve estar em relação à pessoa.

As zonas usam coordenadas **normalizadas** da bounding box da pessoa, com a
origem do I2 (canto inferior esquerdo, máximos exclusivos):

    u = (cx_epi - x_min_pessoa) / largura_pessoa    (0 = esquerda, 1 = direita)
    v = (cy_epi - y_min_pessoa) / altura_pessoa     (0 = base, 1 = topo da cabeça)

Assim, a cabeça fica próxima de `v = 1`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple


def _interval(data: Mapping[str, Any], key: str, context: str) -> Tuple[float, float]:
    values = data[key]
    if not isinstance(values, (list, tuple)) or len(values) != 2:
        raise ValueError(f"{context}.{key}: esperado [min, max]")
    lo, hi = float(values[0]), float(values[1])
    if hi <= lo:
        raise ValueError(f"{context}.{key}: esperado max > min")
    return lo, hi


def _ratio(data: Mapping[str, Any], key: str, context: str, default: float) -> float:
    value = float(data.get(key, default))
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{context}.{key}: esperado valor entre 0 e 1")
    return value


def _weight(data: Mapping[str, Any], key: str, context: str, default: float) -> float:
    value = float(data.get(key, default))
    if value < 0.0:
        raise ValueError(f"{context}.{key}: peso não pode ser negativo")
    return value


@dataclass(frozen=True)
class ZoneRule:
    """Zona esperada (e tolerâncias) de uma classe de EPI, em coordenadas da pessoa."""

    canonical_class: str
    zone: str
    u_min: float
    u_max: float
    v_min: float
    v_max: float
    tolerance_u: float = 0.18
    tolerance_v: float = 0.16
    min_association: float = 0.45
    required: bool = True
    aliases: Tuple[str, ...] = ()

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.u_min + self.u_max) / 2.0, (self.v_min + self.v_max) / 2.0)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], context: str) -> "ZoneRule":
        canonical = str(data["class"])
        ctx = f"{context}.{canonical}"
        u_min, u_max = _interval(data, "u_range", ctx)
        v_min, v_max = _interval(data, "v_range", ctx)
        tolerance_u = float(data.get("tolerance_u", 0.18))
        tolerance_v = float(data.get("tolerance_v", 0.16))
        if tolerance_u <= 0 or tolerance_v <= 0:
            raise ValueError(f"{ctx}: tolerâncias devem ser positivas")

        aliases = tuple(str(a) for a in data.get("aliases", ()))
        return cls(
            canonical_class=canonical,
            zone=str(data.get("zone", canonical)),
            u_min=u_min,
            u_max=u_max,
            v_min=v_min,
            v_max=v_max,
            tolerance_u=tolerance_u,
            tolerance_v=tolerance_v,
            min_association=_ratio(data, "min_association", ctx, 0.45),
            required=bool(data.get("required", True)),
            aliases=aliases,
        )


def _positive(data: Mapping[str, Any], key: str, context: str, default: float) -> float:
    value = float(data.get(key, default))
    if value <= 0.0:
        raise ValueError(f"{context}.{key}: esperado valor positivo")
    return value


@dataclass(frozen=True)
class AssociationSettings:
    """Pesos e limites da associação pessoa <-> EPI.

    A distância métrica (homografia) entra como **corte** e não como score: como
    a H projeta o chão, um capacete na cabeça cai longe do ponto do tronco e
    penalizaria a associação. Por isso `weight_ground` é 0 por padrão e
    `ground_radius_m` é generoso.
    """

    weight_overlap: float = 0.60
    weight_proximity: float = 0.40
    weight_ground: float = 0.0
    expand_x: float = 0.20
    expand_y: float = 0.10
    proximity_sigma_u: float = 0.50
    proximity_tolerance_v: float = 0.25
    ground_radius_m: float = 4.0
    use_ground: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], context: str) -> "AssociationSettings":
        settings = cls(
            weight_overlap=_weight(data, "weight_overlap", context, 0.60),
            weight_proximity=_weight(data, "weight_proximity", context, 0.40),
            weight_ground=_weight(data, "weight_ground", context, 0.0),
            expand_x=_ratio(data, "expand_x", context, 0.20),
            expand_y=_ratio(data, "expand_y", context, 0.10),
            proximity_sigma_u=_ratio(data, "proximity_sigma_u", context, 0.50),
            proximity_tolerance_v=_ratio(data, "proximity_tolerance_v", context, 0.25),
            ground_radius_m=_positive(data, "ground_radius_m", context, 4.0),
            use_ground=bool(data.get("use_ground", True)),
        )
        total = settings.weight_overlap + settings.weight_proximity + settings.weight_ground
        if total <= 0.0:
            raise ValueError(f"{context}: a soma dos pesos precisa ser positiva")
        return settings


@dataclass(frozen=True)
class ConfidenceSettings:
    """Parâmetros de pontuação do estado relacional (heurísticos, ajustáveis)."""

    correct_threshold: float = 0.75
    predicted_factor: float = 0.70
    unknown_state_factor: float = 0.50
    absence_base: float = 0.62
    absence_max: float = 0.70
    absence_candidate_penalty: float = 0.85
    max_confidence: float = 0.95

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], context: str) -> "ConfidenceSettings":
        settings = cls(
            correct_threshold=_ratio(data, "correct_threshold", context, 0.75),
            predicted_factor=_ratio(data, "predicted_factor", context, 0.70),
            unknown_state_factor=_ratio(data, "unknown_state_factor", context, 0.50),
            absence_base=_ratio(data, "absence_base", context, 0.62),
            absence_max=_ratio(data, "absence_max", context, 0.70),
            absence_candidate_penalty=_ratio(data, "absence_candidate_penalty", context, 0.85),
            max_confidence=_ratio(data, "max_confidence", context, 0.95),
        )
        if settings.absence_base > settings.absence_max:
            raise ValueError(f"{context}: absence_base não pode exceder absence_max")
        return settings


@dataclass(frozen=True)
class CalibrationSettings:
    """Critérios de aceitação das calibrações recebidas do I3."""

    max_reprojection_rms_cm: float = 5.0
    min_holdout_points: int = 4

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], context: str) -> "CalibrationSettings":
        return cls(
            max_reprojection_rms_cm=float(data.get("max_reprojection_rms_cm", 5.0)),
            min_holdout_points=int(data.get("min_holdout_points", 4)),
        )


@dataclass(frozen=True)
class EquipmentPolicy:
    """Política completa de EPI carregada da configuração da aplicação."""

    policy_id: str
    version: str
    person_classes: Tuple[str, ...]
    rules: Mapping[str, ZoneRule]
    class_order: Tuple[str, ...]
    association: AssociationSettings
    confidence: ConfidenceSettings
    calibration: CalibrationSettings
    alias_map: Mapping[str, str] = field(default_factory=dict)

    def canonical_for(self, raw_class: str) -> Optional[str]:
        """Classe canônica de um rótulo bruto vindo do I2 (case-insensitive)."""
        return self.alias_map.get(raw_class.strip().lower())

    def is_person(self, raw_class: str) -> bool:
        return raw_class.strip().lower() in self.person_classes

    def rule_for(self, raw_class: str) -> Optional[ZoneRule]:
        canonical = self.canonical_for(raw_class)
        return self.rules.get(canonical) if canonical else None

    def required_classes(self) -> Tuple[str, ...]:
        return tuple(c for c in self.class_order if self.rules[c].required)

    def detect_unknown_class(self, raw_class: str) -> bool:
        """True quando o rótulo não é de pessoa nem consta na política."""
        return not self.is_person(raw_class) and self.canonical_for(raw_class) is None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EquipmentPolicy":
        context = "policy"
        raw_rules = data.get("equipment")
        if not isinstance(raw_rules, list) or not raw_rules:
            raise ValueError("policy.equipment: esperado lista não vazia")

        rules: Dict[str, ZoneRule] = {}
        class_order: list = []
        alias_map: Dict[str, str] = {}

        for item in raw_rules:
            rule = ZoneRule.from_dict(item, context)
            if rule.canonical_class in rules:
                raise ValueError(f"policy.equipment: classe duplicada {rule.canonical_class!r}")
            rules[rule.canonical_class] = rule
            class_order.append(rule.canonical_class)
            for alias in (rule.canonical_class, *rule.aliases):
                key = alias.strip().lower()
                if key in alias_map and alias_map[key] != rule.canonical_class:
                    raise ValueError(f"policy.equipment: alias ambíguo {alias!r}")
                alias_map[key] = rule.canonical_class

        person_classes = tuple(
            str(p).strip().lower() for p in data.get("person_classes", ["pessoa", "person"])
        )
        for person_class in person_classes:
            if person_class in alias_map:
                raise ValueError(f"policy: {person_class!r} é pessoa e não pode ser classe de EPI")

        return cls(
            policy_id=str(data.get("policy_id", "default")),
            version=str(data.get("version", "1.0")),
            person_classes=person_classes,
            rules=rules,
            class_order=tuple(class_order),
            association=AssociationSettings.from_dict(data.get("association", {}), "policy.association"),
            confidence=ConfidenceSettings.from_dict(data.get("confidence", {}), "policy.confidence"),
            calibration=CalibrationSettings.from_dict(data.get("calibration", {}), "policy.calibration"),
            alias_map=alias_map,
        )

    @classmethod
    def from_file(cls, path: "str | Path") -> "EquipmentPolicy":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))
