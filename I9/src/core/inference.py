"""
Classificação relacional geométrica (CORRETO / INCORRETO / AUSENTE).

Para cada pessoa e para cada classe de EPI definida na política:

* EPI associado com score de posicionamento >= `correct_threshold` -> CORRETO;
* EPI associado abaixo do threshold -> INCORRETO (pertence à pessoa, mas está
  fora do lugar esperado);
* nenhum EPI associado -> AUSENTE, com confiança baixa e limitada por
  `absence_max`, já que a ausência não distingue oclusão.

A confiança geométrica é multiplicada pela confiança da detecção do I1 (do EPI,
ou da pessoa no caso de AUSENTE). Um item sai `uncertain` quando a confiança
final fica abaixo de `uncertain_below` ou quando a pessoa está severamente
ocluída por outra pessoa.

O módulo é **stateless**: o cruzamento temporal é responsabilidade do S2.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Tuple

from src.core.geometry import normalized_position, zone_score
from src.domain.body_zones import ZoneGeometry
from src.domain.models import (
    Detection,
    EquipmentEvaluation,
    EquipmentMatch,
    PairingResult,
    PersonEvaluation,
    PersonRelation,
    RelationalState,
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

        persons = [relation.person for relation in pairing.relations]
        return [
            self._infer_person(relation, dangling, self._uncertain_reasons(relation.person, persons))
            for relation in pairing.relations
        ]

    def _uncertain_reasons(self, person: Detection, persons: List[Detection]) -> Tuple[str, ...]:
        """Motivos que tornam incerta toda a avaliação da pessoa no quadro."""
        threshold = self.policy.confidence.occlusion_overlap
        for other in persons:
            if other.detection_id == person.detection_id:
                continue
            if other.bbox.containment(person.bbox) >= threshold:
                return ("severe_occlusion",)
        return ()

    def _infer_person(
        self, relation: PersonRelation, dangling: Dict[str, float], reasons: Tuple[str, ...]
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

        if reasons:
            evaluations = [replace(e, uncertain=True) for e in evaluations]
        return PersonEvaluation(
            person=relation.person, equipment=tuple(evaluations), uncertain_reasons=reasons
        )

    def _zone_geometry(self, canonical: str, person_bbox=None) -> ZoneGeometry:
        """Geometria da zona, considerando zonas customizadas e aspect ratio.
        
        Se person_bbox é fornecido, ajusta as tolerâncias baseado na razão de
        aspecto (largura/altura) da bbox da pessoa.
        """
        rule = self.policy.rules[canonical]
        base_geometry = rule.geometry
        
        # Usa zonas customizadas da política se disponíveis
        if rule.zone in self.policy.custom_zones:
            base_geometry = self.policy.custom_zones[rule.zone]
        
        # Se não temos bbox da pessoa, retorna a geometria base
        if person_bbox is None:
            return base_geometry
        
        # Calcula razão de aspecto
        aspect_ratio = person_bbox.width / person_bbox.height if person_bbox.height > 0 else 1.0
        
        # Ajusta tolerâncias baseado no aspect ratio
        if aspect_ratio >= 1.0:  # Pessoa deitada ou estendida
            tol_u = base_geometry.tolerance_u * 1.3  # expande para laterais
            tol_v = base_geometry.tolerance_v * 1.5  # expande para baixo
        else:  # Pessoa em pé
            tol_u = base_geometry.tolerance_u
            tol_v = base_geometry.tolerance_v
        
        return ZoneGeometry(
            u_min=base_geometry.u_min,
            u_max=base_geometry.u_max,
            v_min=base_geometry.v_min,
            v_max=base_geometry.v_max,
            tolerance_u=tol_u,
            tolerance_v=tol_v,
        )

    def _evaluate_detected(
        self,
        person: Detection,
        canonical: str,
        required: bool,
        match: EquipmentMatch,
    ) -> EquipmentEvaluation:
        rule = self.policy.rules[canonical]
        zone_geometry = self._zone_geometry(canonical, person.bbox)
        u, v = normalized_position(match.detection.bbox, person.bbox)
        placement = zone_score(u, v, zone_geometry)

        if placement >= self.policy.confidence.correct_threshold:
            state = RelationalState.CORRETO
            confidence = match.association_score * placement
        else:
            state = RelationalState.INCORRETO
            confidence = match.association_score * (1.0 - placement)

        confidence = min(self.policy.confidence.max_confidence, max(0.0, confidence))
        confidence *= match.detection.confidence
        evidence: Dict[str, object] = {
            "association_score": round(match.association_score, 4),
            "placement_score": round(placement, 4),
            "detection_confidence": match.detection.confidence,
            "person_normalized_center": {"u": round(u, 4), "v": round(v, 4)},
            "expected_zone": rule.zone.value,
        }
        if match.ground_distance_m is not None:
            evidence["ground_distance_m"] = round(match.ground_distance_m, 3)

        return EquipmentEvaluation(
            canonical_class=canonical,
            required=required,
            state=state,
            confidence=confidence,
            detection=match.detection,
            uncertain=self._is_uncertain(confidence),
            evidence=evidence,
        )

    def _evaluate_missing(
        self, person: Detection, canonical: str, dangling_factor: float
    ) -> EquipmentEvaluation:
        confidence = self.policy.confidence.absence_base * dangling_factor
        confidence = min(self.policy.confidence.absence_max, confidence) * person.confidence
        confidence = max(0.0, confidence)
        return EquipmentEvaluation(
            canonical_class=canonical,
            required=True,
            state=RelationalState.AUSENTE,
            confidence=confidence,
            detection=None,
            uncertain=self._is_uncertain(confidence),
            evidence={
                "reason": "no_candidate_in_person_region",
                "zone": self.policy.rules[canonical].zone.value,
            },
        )

    def _is_uncertain(self, confidence: float) -> bool:
        return confidence < self.policy.confidence.uncertain_below
