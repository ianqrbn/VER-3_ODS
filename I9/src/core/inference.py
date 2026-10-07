"""
Classificação relacional geométrica (CORRETO / INCORRETO / AUSENTE).

Para cada pessoa e para cada classe de EPI definida na política:

* EPI associado com score de posicionamento >= `correct_threshold` -> CORRETO;
* EPI associado abaixo do threshold -> INCORRETO (pertence à pessoa, mas está
  fora do lugar esperado);
* nenhum EPI associado -> AUSENTE, com confiança baixa e limitada por
  `absence_max`, já que não existe informação de oclusão no contrato.

O módulo é **stateless**: nenhuma regra temporal é aplicada aqui, conforme a
responsabilidade definida para o componente de rastreio (I2).
"""

from __future__ import annotations

from typing import Dict, List

from src.core.geometry import normalized_position, zone_score
from src.domain.body_zones import ZoneGeometry
from src.domain.models import (
    EquipmentEvaluation,
    EquipmentMatch,
    PairingResult,
    PersonEvaluation,
    PersonRelation,
    RelationalState,
    Track,
    TrackState,
)
from src.domain.policy import EquipmentPolicy


class RelationInferenceModule:
    def __init__(self, policy: EquipmentPolicy):
        self.policy = policy

    def infer(self, pairing: PairingResult) -> List[PersonEvaluation]:
        # candidatos do mesmo tipo que ficaram sem dono reduzem a confiança
        # de um eventual AUSENTE: existe evidência de que algo existe no frame.
        dangling = {
            item.canonical_class: self.policy.confidence.absence_candidate_penalty
            for item in pairing.unassociated_equipment
        }

        return [self._infer_person(relation, dangling) for relation in pairing.relations]

    def _infer_person(
        self, relation: PersonRelation, dangling: Dict[str, float]
    ) -> PersonEvaluation:
        matches = {match.canonical_class: match for match in relation.equipment}
        evaluations: List[EquipmentEvaluation] = []

        for canonical in self.policy.class_order:
            rule = self.policy.rules[canonical]
            match = matches.get(canonical)
            if match is not None:
                evaluations.append(
                    self._evaluate_detected(relation.person, canonical, rule.required, match)
                )
            elif rule.required:
                evaluations.append(
                    self._evaluate_missing(
                        relation.person, canonical, dangling.get(canonical, 1.0)
                    )
                )

        return PersonEvaluation(person=relation.person, equipment=tuple(evaluations))

    def _zone_geometry(self, canonical: str) -> ZoneGeometry:
        """Geometria da zona, considerando zonas customizadas da política."""
        rule = self.policy.rules[canonical]
        if rule.zone in self.policy.custom_zones:
            return self.policy.custom_zones[rule.zone]
        return rule.geometry

    def _evaluate_detected(
        self,
        person: Track,
        canonical: str,
        required: bool,
        match: EquipmentMatch,
    ) -> EquipmentEvaluation:
        rule = self.policy.rules[canonical]
        zone_geometry = self._zone_geometry(canonical)
        u, v = normalized_position(match.track.bbox, person.bbox)
        placement = zone_score(u, v, zone_geometry)
        factor = self._state_factor(match.track)

        if placement >= self.policy.confidence.correct_threshold:
            state = RelationalState.CORRETO
            confidence = match.association_score * placement
        else:
            state = RelationalState.INCORRETO
            confidence = match.association_score * (1.0 - placement)

        confidence *= factor
        ceiling = self.policy.confidence.max_confidence
        evidence: Dict[str, object] = {
            "association_score_pct": round(match.association_score * 100.0, 2),
            "placement_score_pct": round(placement * 100.0, 2),
            "person_normalized_center": {"u": round(u, 4), "v": round(v, 4)},
            "expected_zone": rule.zone.value,
        }
        if match.ground_distance_m is not None:
            evidence["ground_distance_m"] = round(match.ground_distance_m, 3)
        if match.track.state is not TrackState.CONFIRMED:
            evidence["penalty"] = self._penalty_name(match.track)

        return EquipmentEvaluation(
            canonical_class=canonical,
            required=required,
            state=state,
            confidence_pct=min(ceiling, max(0.0, confidence)) * 100.0,
            track=match.track,
            evidence=evidence,
        )

    def _evaluate_missing(
        self, person: Track, canonical: str, dangling_factor: float
    ) -> EquipmentEvaluation:
        confidence = (
            self.policy.confidence.absence_base
            * dangling_factor
            * self._state_factor(person)
        )
        confidence = min(self.policy.confidence.absence_max, confidence)
        return EquipmentEvaluation(
            canonical_class=canonical,
            required=True,
            state=RelationalState.AUSENTE,
            confidence_pct=max(0.0, confidence * 100.0),
            track=None,
            evidence={
                "reason": "no_candidate_in_person_region",
                "zone": self.policy.rules[canonical].zone.value,
            },
        )

    def _state_factor(self, track: Track) -> float:
        settings = self.policy.confidence
        if track.state is TrackState.CONFIRMED:
            return 1.0
        if track.state is TrackState.PREDICTED:
            return settings.predicted_factor
        return settings.unknown_state_factor

    @staticmethod
    def _penalty_name(track: Track) -> str:
        if track.state is TrackState.PREDICTED:
            return "predicted_track"
        return "unknown_track_state"
