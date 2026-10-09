"""
Política de EPI: define, por aplicação, quais classes de equipamento existem,
quais são obrigatórias e em qual **zona do corpo** cada uma deve ser usada.

A geometria de cada zona não vive aqui: é conhecimento de domínio do verificador e
está em `src/domain/body_zones.py`. A configuração carrega apenas a referência,
por exemplo:

    { "class": "CAPACETES", "zone": "HEAD", "required": true, "aliases": [...] }

Os parâmetros numéricos de associação e de confiança continuam disponíveis para
ajuste fino, mas todos têm default no motor e são opcionais.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from src.domain.body_zones import BodyZone, ZoneGeometry, get_zone, resolve_zone


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


def _positive(data: Mapping[str, Any], key: str, context: str, default: float) -> float:
    value = float(data.get(key, default))
    if value <= 0.0:
        raise ValueError(f"{context}.{key}: esperado valor positivo")
    return value


@dataclass(frozen=True)
class ZoneRule:
    """Regra de uma classe de EPI: qual zona do corpo ela deve ocupar."""

    canonical_class: str
    zone: BodyZone
    required: bool = True
    min_association: float = 0.45
    aliases: Tuple[str, ...] = ()

    @property
    def geometry(self) -> ZoneGeometry:
        """Geometria da zona, resolvida no registro do motor."""
        return get_zone(self.zone)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], context: str) -> "ZoneRule":
        if "class" not in data:
            raise ValueError(f"{context}.equipment: campo obrigatório ausente -> 'class'")
        canonical = str(data["class"])
        ctx = f"{context}.{canonical}"
        if "zone" not in data:
            raise ValueError(f"{ctx}: campo obrigatório ausente -> 'zone'")

        return cls(
            canonical_class=canonical,
            zone=resolve_zone(data["zone"]),
            required=bool(data.get("required", True)),
            min_association=_ratio(data, "min_association", ctx, 0.45),
            aliases=tuple(str(a) for a in data.get("aliases", ())),
        )


@dataclass(frozen=True)
class AssociationSettings:
    """Configurações da associação pessoa <-> EPI.

    A associação usa distância radial (Euclidiana) entre centroides normalizada
    pela diagonal da bbox da pessoa, com decaimento gaussiano controlado por
    `radial_sigma`.
    """

    radial_sigma: float = 0.80  # controle do raio de captura (em múltiplos da diagonal)
    weight_overlap: float = 0.60  # legado: não usado na associação radial
    weight_proximity: float = 0.40  # legado: não usado na associação radial
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
            radial_sigma=_positive(data, "radial_sigma", context, 0.80),
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
    custom_zones: Mapping[BodyZone, ZoneGeometry] = field(default_factory=dict)

    def canonical_for(self, raw_class: str) -> Optional[str]:
        """Classe canônica de um rótulo bruto vindo do I2 (case-insensitive)."""
        return self.alias_map.get(raw_class.strip().lower())

    def is_person(self, raw_class: str) -> bool:
        return raw_class.strip().lower() in self.person_classes

    def rule_for(self, raw_class: str) -> Optional[ZoneRule]:
        canonical = self.canonical_for(raw_class)
        return self.rules.get(canonical) if canonical else None

    def zone_for(self, raw_class: str) -> Optional[BodyZone]:
        rule = self.rule_for(raw_class)
        return rule.zone if rule else None

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

        # Processa zonas customizadas (para calibração)
        custom_zones: Dict[BodyZone, ZoneGeometry] = {}
        zones_raw = data.get("zones", {})
        if isinstance(zones_raw, dict):
            for zone_name, zone_data in zones_raw.items():
                try:
                    zone = resolve_zone(zone_name)
                    custom_zones[zone] = ZoneGeometry(
                        u_min=float(zone_data["u_min"]),
                        u_max=float(zone_data["u_max"]),
                        v_min=float(zone_data["v_min"]),
                        v_max=float(zone_data["v_max"]),
                        tolerance_u=float(zone_data.get("tolerance_u", 0.18)),
                        tolerance_v=float(zone_data.get("tolerance_v", 0.16)),
                    )
                except (KeyError, ValueError) as exc:
                    raise ValueError(f"policy.zones.{zone_name}: {exc}") from exc

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
            custom_zones=custom_zones,
        )

    @classmethod
    def from_file(cls, path: "str | Path") -> "EquipmentPolicy":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))
