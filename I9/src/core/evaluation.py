"""
Avaliação do pipeline I9 contra dataset annotado.

Compara as predições (RelationalEvent) com o ground truth (AnnotatedFrame)
e calcula métricas de classificação: precision, recall, F1 por classe e
F1 macro (média não ponderada de CORRETO, INCORRETO, AUSENTE).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.domain.models import (
    AnnotatedFrame,
    EquipmentEvaluation,
    PersonEvaluation,
    RelationalEvent,
    RelationalState,
)


@dataclass(frozen=True)
class ClassMetrics:
    """Métricas de uma classe (CORRETO, INCORRETO ou AUSENTE)."""

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p = self.precision
        r = self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    def as_dict(self) -> Dict[str, float]:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "support": self.true_positives + self.false_negatives,
        }


@dataclass(frozen=True)
class EvaluationResult:
    """Resultado da avaliação de um dataset."""

    per_class: Dict[RelationalState, ClassMetrics] = field(default_factory=dict)
    confusion_matrix: Dict[Tuple[RelationalState, RelationalState], int] = field(default_factory=dict)
    total_predictions: int = 0
    total_ground_truth: int = 0

    @property
    def f1_macro(self) -> float:
        """F1 macro: média não ponderada do F1 de cada classe."""
        if not self.per_class:
            return 0.0
        return sum(m.f1 for m in self.per_class.values()) / len(self.per_class)

    @property
    def accuracy(self) -> float:
        """Acurácia: predições corretas / total."""
        if self.total_predictions == 0:
            return 0.0
        correct = sum(m.true_positives for m in self.per_class.values())
        return correct / self.total_predictions

    def as_dict(self) -> Dict:
        return {
            "f1_macro": round(self.f1_macro, 4),
            "accuracy": round(self.accuracy, 4),
            "per_class": {
                state.value: metrics.as_dict() for state, metrics in self.per_class.items()
            },
            "confusion_matrix": {
                f"{actual.value}_as_{predicted.value}": count
                for (actual, predicted), count in self.confusion_matrix.items()
            },
            "total_predictions": self.total_predictions,
            "total_ground_truth": self.total_ground_truth,
        }


class EvaluationModule:
    """Compara predições do pipeline com ground truth annotado."""

    def __init__(self, policy: Any):
        self.policy = policy

    def evaluate(
        self,
        predictions: List[RelationalEvent],
        ground_truth: List[AnnotatedFrame],
    ) -> EvaluationResult:
        """Avalia as predições contra o ground truth.

        Args:
            predictions: eventos de saída do pipeline (um por frame)
            ground_truth: frames anotados com ground truth

        Returns:
            EvaluationResult com métricas por classe e F1 macro
        """
        gt_by_frame = {(g.camera_id, g.frame): g for g in ground_truth}

        # Contadores mutáveis (serão convertidos para ClassMetrics no final)
        tp: Dict[RelationalState, int] = {state: 0 for state in RelationalState}
        fp: Dict[RelationalState, int] = {state: 0 for state in RelationalState}
        fn: Dict[RelationalState, int] = {state: 0 for state in RelationalState}
        confusion: Dict[Tuple[RelationalState, RelationalState], int] = {}
        total_pred = 0
        total_gt = 0

        for pred in predictions:
            gt = gt_by_frame.get((pred.camera_id, pred.frame))
            if gt is None:
                continue

            # Mapeia ground truth por (person_track_id, canonical_class)
            gt_map = self._build_gt_map(gt)

            for person_eval in pred.relations:
                for equip_eval in person_eval.equipment:
                    predicted_state = equip_eval.state
                    gt_state = gt_map.get(
                        (person_eval.person.track_id, equip_eval.canonical_class)
                    )

                    total_pred += 1
                    if gt_state is not None:
                        total_gt += 1

                    # Atualiza contadores
                    if gt_state is not None:
                        if predicted_state == gt_state:
                            tp[gt_state] += 1
                        else:
                            fp[predicted_state] += 1
                            fn[gt_state] += 1
                            key = (gt_state, predicted_state)
                            confusion[key] = confusion.get(key, 0) + 1
                    else:
                        # Ground truth não tem essa classe (ex.: EPI opcional)
                        fp[predicted_state] += 1

        # Converte contadores para ClassMetrics
        per_class = {
            state: ClassMetrics(
                true_positives=tp[state],
                false_positives=fp[state],
                false_negatives=fn[state],
            )
            for state in RelationalState
        }

        return EvaluationResult(
            per_class=per_class,
            confusion_matrix=confusion,
            total_predictions=total_pred,
            total_ground_truth=total_gt,
        )

    def _build_gt_map(
        self, gt: AnnotatedFrame
    ) -> Dict[Tuple[int, str], RelationalState]:
        """Mapeia (person_track_id, canonical_class) -> RelationalState.

        Para cada pessoa no ground truth, encontra o EPI correspondente
        e seu estado relacional anotado. Usa a política para mapear o nome
        bruto da classe para o nome canônico.
        """
        result: Dict[Tuple[int, str], RelationalState] = {}

        # Separa pessoas e EPIs
        persons = [t for t in gt.tracks if t.relational_state is None]
        epis = [t for t in gt.tracks if t.relational_state is not None]

        for person in persons:
            for epi in epis:
                # Mapeia nome bruto para nome canônico usando a política
                canonical = self.policy.canonical_for(epi.raw_class)
                if canonical:
                    result[(person.track_id, canonical)] = epi.relational_state

        return result
