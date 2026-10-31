"""
Associação geométrica entre pessoas e EPIs de um único quadro.

Estratégia:

1. separar as detecções do I1 em pessoas, EPIs conhecidos e descartadas
   (confiança abaixo de `min_detection_confidence` ou classes fora da política);
2. para cada classe de EPI, pontuar todos os pares pessoa x EPI usando
   proximidade radial ao centro da pessoa e, quando existe calibração válida,
   a distância no plano do ambiente;
3. resolver o casamento de forma **um-para-um** (EPIs são individuais) por
   atribuição gulosa determinística sobre os candidatos ordenados.

Nenhuma decisão temporal é tomada aqui: cada detecção vale apenas para o quadro
corrente (o cruzamento temporal é do S2). A ausência é tratada na inferência.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from src.core.calibration import CalibrationStore
from src.core.geometry import (
    ground_distance_m,
    normalized_position,
    overlap_score,
    person_relative_proximity,
)
from src.domain.models import (
    Detection,
    DetectionFrame,
    EquipmentMatch,
    IgnoredDetection,
    PairingResult,
    PersonRelation,
    UnassociatedEquipment,
)
from src.domain.policy import EquipmentPolicy, ZoneRule


class PairingModule:
    def __init__(self, policy: EquipmentPolicy, calibration_store: Optional[CalibrationStore] = None):
        self.policy = policy
        self.calibration_store = calibration_store

    def pair(self, frame: DetectionFrame) -> PairingResult:
        persons, candidates, ignored = self._classify_detections(frame)

        calibration = self.calibration_store.get(frame.source_id) if self.calibration_store else None
        matrix = calibration.homography if calibration else None
        meters_per_unit = calibration.meters_per_unit if calibration else 1.0

        by_class: Dict[str, List[Detection]] = {}
        for detection in candidates:
            canonical = self.policy.canonical_for(detection.raw_class)
            if canonical:
                by_class.setdefault(canonical, []).append(detection)

        matches: Dict[int, List[EquipmentMatch]] = {p.detection_id: [] for p in persons}
        unassociated: List[UnassociatedEquipment] = []

        for canonical in self.policy.class_order:
            detections = by_class.get(canonical, [])
            if not detections:
                continue
            rule = self.policy.rules[canonical]
            assigned, leftovers = self._match_class(persons, detections, rule, matrix, meters_per_unit)
            for person_id, match in assigned.items():
                matches[person_id].append(match)
            for detection, best_score in leftovers:
                unassociated.append(
                    UnassociatedEquipment(
                        canonical_class=canonical,
                        detection=detection,
                        reason=(
                            "below_association_threshold" if best_score > 0.0 else "no_person_in_reach"
                        ),
                        best_association_score=best_score,
                    )
                )

        relations = [
            PersonRelation(person=person, equipment=tuple(matches[person.detection_id]))
            for person in persons
        ]
        unassociated.sort(key=lambda item: item.detection.detection_id)
        ignored.sort(key=lambda item: item.detection.detection_id)
        return PairingResult(
            relations=relations, unassociated_equipment=unassociated, ignored_detections=ignored
        )

    def _classify_detections(
        self, frame: DetectionFrame
    ) -> Tuple[List[Detection], List[Detection], List[IgnoredDetection]]:
        persons: List[Detection] = []
        candidates: List[Detection] = []
        ignored: List[IgnoredDetection] = []
        min_confidence = self.policy.confidence.min_detection_confidence

        for detection in frame.detections:
            if detection.confidence < min_confidence:
                ignored.append(IgnoredDetection(detection=detection, reason="low_detection_confidence"))
            elif self.policy.is_person(detection.raw_class):
                persons.append(detection)
            elif self.policy.canonical_for(detection.raw_class) is not None:
                candidates.append(detection)
            else:
                ignored.append(IgnoredDetection(detection=detection, reason="class_not_in_policy"))

        persons.sort(key=lambda d: d.detection_id)
        candidates.sort(key=lambda d: d.detection_id)
        return persons, candidates, ignored

    def _association_score(
        self,
        person: Detection,
        candidate: Detection,
        matrix,
        meters_per_unit: float,
    ) -> Tuple[float, Optional[float]]:
        """Score de associação em [0, 1] baseado em distância radial (Euclidiana).

        A associação agora confia na distância radial entre centroides normalizada
        pela diagonal da bbox da pessoa, sem usar overlap de bounding box.
        """
        settings = self.policy.association

        # Distância Euclidiana entre centroides
        dx = candidate.bbox.center_x - person.bbox.center_x
        dy = candidate.bbox.center_y - person.bbox.center_y
        distance = math.sqrt(dx * dx + dy * dy)

        # Normaliza pela diagonal da bbox da pessoa
        diagonal = math.sqrt(person.bbox.width ** 2 + person.bbox.height ** 2)
        if diagonal == 0:
            return 0.0, None
        normalized_distance = distance / diagonal

        # Score gaussiano: 1.0 quando distância = 0, decai suavemente
        sigma = settings.radial_sigma
        score = math.exp(-0.5 * (normalized_distance / sigma) ** 2)

        # Distância métrica (para informação, não usada no score)
        ground_m: Optional[float] = None
        if matrix is not None:
            ground_m = ground_distance_m(matrix, person.center, candidate.center, meters_per_unit)

        return min(1.0, max(0.0, score)), ground_m

    def _match_class(
        self,
        persons: List[Detection],
        detections: List[Detection],
        rule: ZoneRule,
        matrix,
        meters_per_unit: float,
    ) -> Tuple[Dict[int, EquipmentMatch], List[Tuple[Detection, float]]]:
        scored: List[Tuple[float, int, Detection, Optional[float]]] = []
        best_for_detection: Dict[int, float] = {d.detection_id: 0.0 for d in detections}

        for person in persons:
            for candidate in detections:
                score, ground_m = self._association_score(person, candidate, matrix, meters_per_unit)
                if score <= 0.0:
                    continue
                best_for_detection[candidate.detection_id] = max(
                    best_for_detection[candidate.detection_id], score
                )
                if score >= rule.min_association:
                    scored.append((score, person.detection_id, candidate, ground_m))

        # maior score primeiro; desempate estável por detection_id
        scored.sort(key=lambda item: (-item[0], item[1], item[2].detection_id))

        assigned: Dict[int, EquipmentMatch] = {}
        used_persons: set = set()
        used_detections: set = set()
        for score, person_id, candidate, ground_m in scored:
            if person_id in used_persons or candidate.detection_id in used_detections:
                continue
            used_persons.add(person_id)
            used_detections.add(candidate.detection_id)
            assigned[person_id] = EquipmentMatch(
                canonical_class=rule.canonical_class,
                required=rule.required,
                detection=candidate,
                association_score=score,
                ground_distance_m=ground_m,
            )

        leftovers = [
            (detection, best_for_detection[detection.detection_id])
            for detection in detections
            if detection.detection_id not in used_detections
        ]
        return assigned, leftovers
