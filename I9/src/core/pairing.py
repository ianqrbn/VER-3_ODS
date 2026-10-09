"""
Associação geométrica entre pessoas e EPIs de um único frame.

Estratégia:

1. separar os tracks em pessoas, EPIs conhecidos e descartados (`lost` ou
   classes fora da política);
2. para cada classe de EPI, pontuar todos os pares pessoa x EPI usando
   sobreposição de caixas, proximidade ao centro da pessoa e, quando existe
   calibração válida, a distância no plano do ambiente;
3. resolver o casamento de forma **um-para-um** (EPIs são individuais) por
   atribuição gulosa determinística sobre os candidatos ordenados.

Nenhuma decisão temporal é tomada aqui: cada track vale apenas para o frame
corrente. A ausência é tratada na inferência, não aqui.
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
    EquipmentMatch,
    IgnoredTrack,
    PairingResult,
    PersonRelation,
    Track,
    TrackState,
    TrackingFrame,
    UnassociatedEquipment,
)
from src.domain.policy import EquipmentPolicy, ZoneRule


class PairingModule:
    def __init__(self, policy: EquipmentPolicy, calibration_store: Optional[CalibrationStore] = None):
        self.policy = policy
        self.calibration_store = calibration_store

    def pair(self, frame: TrackingFrame) -> PairingResult:
        persons, candidates, ignored = self._classify_tracks(frame)

        calibration = self.calibration_store.get(frame.camera_id) if self.calibration_store else None
        matrix = calibration.homography if calibration else None
        meters_per_unit = calibration.meters_per_unit if calibration else 1.0

        by_class: Dict[str, List[Track]] = {}
        for track in candidates:
            canonical = self.policy.canonical_for(track.raw_class)
            if canonical:
                by_class.setdefault(canonical, []).append(track)

        matches: Dict[int, List[EquipmentMatch]] = {p.track_id: [] for p in persons}
        unassociated: List[UnassociatedEquipment] = []

        for canonical in self.policy.class_order:
            tracks = by_class.get(canonical, [])
            if not tracks:
                continue
            rule = self.policy.rules[canonical]
            assigned, leftovers = self._match_class(persons, tracks, rule, matrix, meters_per_unit)
            for person_id, match in assigned.items():
                matches[person_id].append(match)
            for track, best_score in leftovers:
                unassociated.append(
                    UnassociatedEquipment(
                        canonical_class=canonical,
                        track=track,
                        reason=(
                            "below_association_threshold" if best_score > 0.0 else "no_person_in_reach"
                        ),
                        best_association_score_pct=best_score * 100.0,
                    )
                )

        relations = [
            PersonRelation(person=person, equipment=tuple(matches[person.track_id]))
            for person in persons
        ]
        unassociated.sort(key=lambda item: item.track.track_id)
        ignored.sort(key=lambda item: item.track.track_id)
        return PairingResult(relations=relations, unassociated_equipment=unassociated, ignored_tracks=ignored)

    def _classify_tracks(
        self, frame: TrackingFrame
    ) -> Tuple[List[Track], List[Track], List[IgnoredTrack]]:
        persons: List[Track] = []
        candidates: List[Track] = []
        ignored: List[IgnoredTrack] = []

        for track in frame.tracks:
            if track.state is TrackState.LOST:
                ignored.append(IgnoredTrack(track=track, reason="track_state_lost"))
            elif self.policy.is_person(track.raw_class):
                persons.append(track)
            elif self.policy.canonical_for(track.raw_class) is not None:
                candidates.append(track)
            else:
                ignored.append(IgnoredTrack(track=track, reason="class_not_in_policy"))

        persons.sort(key=lambda t: t.track_id)
        candidates.sort(key=lambda t: t.track_id)
        return persons, candidates, ignored

    def _association_score(
        self,
        person: Track,
        candidate: Track,
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
        persons: List[Track],
        tracks: List[Track],
        rule: ZoneRule,
        matrix,
        meters_per_unit: float,
    ) -> Tuple[Dict[int, EquipmentMatch], List[Tuple[Track, float]]]:
        scored: List[Tuple[float, int, Track, Optional[float]]] = []
        best_for_track: Dict[int, float] = {t.track_id: 0.0 for t in tracks}

        for person in persons:
            for candidate in tracks:
                score, ground_m = self._association_score(person, candidate, matrix, meters_per_unit)
                if score <= 0.0:
                    continue
                best_for_track[candidate.track_id] = max(
                    best_for_track[candidate.track_id], score
                )
                if score >= rule.min_association:
                    scored.append((score, person.track_id, candidate, ground_m))

        # maior score primeiro; desempate estável por track_id
        scored.sort(key=lambda item: (-item[0], item[1], item[2].track_id))

        assigned: Dict[int, EquipmentMatch] = {}
        used_persons: set = set()
        used_tracks: set = set()
        for score, person_id, candidate, ground_m in scored:
            if person_id in used_persons or candidate.track_id in used_tracks:
                continue
            used_persons.add(person_id)
            used_tracks.add(candidate.track_id)
            assigned[person_id] = EquipmentMatch(
                canonical_class=rule.canonical_class,
                required=rule.required,
                track=candidate,
                association_score=score,
                ground_distance_m=ground_m,
            )

        leftovers = [
            (track, best_for_track[track.track_id])
            for track in tracks
            if track.track_id not in used_tracks
        ]
        return assigned, leftovers
