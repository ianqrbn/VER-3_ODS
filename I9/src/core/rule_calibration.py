"""
Calibração das regras geométricas por grid search em etapas.

Para evitar explosão combinatória, a calibração é feita em etapas:
  1. Associação (weight_overlap, weight_proximity, etc.)
  2. Geometria das zonas (HEAD, TORSO, HANDS)
  3. Thresholds de confiança (correct_threshold, absence_base, etc.)

Cada etapa usa os melhores parâmetros da etapa anterior.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.evaluation import EvaluationModule, EvaluationResult
from src.core.inference import RelationInferenceModule
from src.core.pairing import PairingModule
from src.core.pipeline import I9Pipeline
from src.domain.models import AnnotatedFrame, RelationalEvent
from src.domain.policy import EquipmentPolicy


@dataclass(frozen=True)
class CalibrationResult:
    """Resultado da calibração."""

    best_policy: EquipmentPolicy
    best_f1_macro: float
    best_params: Dict[str, Any]
    history: List[Dict[str, Any]] = field(default_factory=list)

    def save_report(self, path: str) -> None:
        """Salva relatório de calibração em JSON."""
        report = {
            "best_f1_macro": round(self.best_f1_macro, 4),
            "best_params": self.best_params,
            "history": self.history,
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)

    def save_policy(self, path: str) -> None:
        """Salva a melhor política em JSON."""
        policy_dict = {
            "policy_id": self.best_policy.policy_id,
            "version": self.best_policy.version,
            "person_classes": list(self.best_policy.person_classes),
            "equipment": [
                {
                    "class": rule.canonical_class,
                    "zone": rule.zone.value,
                    "required": rule.required,
                    "min_association": rule.min_association,
                    "aliases": list(rule.aliases),
                }
                for rule in self.best_policy.rules.values()
            ],
            "association": {
                "weight_overlap": self.best_policy.association.weight_overlap,
                "weight_proximity": self.best_policy.association.weight_proximity,
                "weight_ground": self.best_policy.association.weight_ground,
                "expand_x": self.best_policy.association.expand_x,
                "expand_y": self.best_policy.association.expand_y,
                "proximity_sigma_u": self.best_policy.association.proximity_sigma_u,
                "proximity_tolerance_v": self.best_policy.association.proximity_tolerance_v,
                "ground_radius_m": self.best_policy.association.ground_radius_m,
                "use_ground": self.best_policy.association.use_ground,
            },
            "confidence": {
                "correct_threshold": self.best_policy.confidence.correct_threshold,
                "predicted_factor": self.best_policy.confidence.predicted_factor,
                "unknown_state_factor": self.best_policy.confidence.unknown_state_factor,
                "absence_base": self.best_policy.confidence.absence_base,
                "absence_max": self.best_policy.confidence.absence_max,
                "absence_candidate_penalty": self.best_policy.confidence.absence_candidate_penalty,
                "max_confidence": self.best_policy.confidence.max_confidence,
            },
            "calibration": {
                "max_reprojection_rms_cm": self.best_policy.calibration.max_reprojection_rms_cm,
                "min_holdout_points": self.best_policy.calibration.min_holdout_points,
            },
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(policy_dict, handle, ensure_ascii=False, indent=2)


class RuleCalibrationModule:
    """Calibra parâmetros das regras geométricas por grid search em etapas."""

    def __init__(self, base_policy: EquipmentPolicy):
        self.base_policy = base_policy
        self.evaluator = EvaluationModule(base_policy)

    def calibrate(
        self,
        dataset: List[AnnotatedFrame],
        param_grid: Dict[str, List[Any]],
        zones: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> CalibrationResult:
        """Executa grid search em etapas sobre os parâmetros.

        Args:
            dataset: frames anotados com ground truth
            param_grid: dicionário de parâmetros -> lista de valores
            zones: geometria das zonas do corpo (opcional, para calibrar zonas)

        Returns:
            CalibrationResult com melhor política e histórico
        """
        # Separa parâmetros por etapa
        assoc_params = {k: v for k, v in param_grid.items() if k in self._assoc_param_names()}
        conf_params = {k: v for k, v in param_grid.items() if k in self._conf_param_names()}

        current_policy = self.base_policy
        current_params: Dict[str, Any] = {}
        history: List[Dict[str, Any]] = []

        # Etapa 1: Associação
        if assoc_params:
            current_policy, current_params, stage_history = self._calibrate_stage(
                current_policy, assoc_params, dataset, "association"
            )
            history.extend(stage_history)

        # Etapa 2: Zonas (calibra cada zona separadamente para evitar explosão combinatória)
        if zones:
            for zone_name, zone_grid in zones.items():
                zone_params = {
                    f"zone_{zone_name}_{param_name}": values
                    for param_name, values in zone_grid.items()
                }
                current_policy, zone_best_params, stage_history = self._calibrate_stage(
                    current_policy, zone_params, dataset, f"zone_{zone_name}", zones=zones
                )
                current_params.update(zone_best_params)
                history.extend(stage_history)

        # Etapa 3: Confiança
        if conf_params:
            current_policy, current_params, stage_history = self._calibrate_stage(
                current_policy, conf_params, dataset, "confidence"
            )
            history.extend(stage_history)

        # Avaliação final
        final_f1 = self._evaluate_policy(current_policy, dataset)

        return CalibrationResult(
            best_policy=current_policy,
            best_f1_macro=final_f1,
            best_params=current_params,
            history=history,
        )

    def _calibrate_stage(
        self,
        base_policy: EquipmentPolicy,
        param_grid: Dict[str, List[Any]],
        dataset: List[AnnotatedFrame],
        stage_name: str,
        zones: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Tuple[EquipmentPolicy, Dict[str, Any], List[Dict[str, Any]]]:
        """Calibra uma etapa de parâmetros."""
        import itertools

        keys = list(param_grid.keys())
        values = [param_grid[k] for k in keys]
        combinations = list(itertools.product(*values))

        best_f1 = -1.0
        best_params: Dict[str, Any] = {}
        best_policy: Optional[EquipmentPolicy] = None
        history: List[Dict[str, Any]] = []

        for i, combo in enumerate(combinations):
            params = dict(zip(keys, combo))

            try:
                policy = self._build_policy(base_policy, params, zones)
                f1 = self._evaluate_policy(policy, dataset)

                history.append({
                    "stage": stage_name,
                    "iteration": i,
                    "params": {k: v for k, v in params.items()},
                    "f1_macro": round(f1, 4),
                })

                if f1 > best_f1:
                    best_f1 = f1
                    best_params = params
                    best_policy = policy

            except Exception as exc:
                history.append({
                    "stage": stage_name,
                    "iteration": i,
                    "params": {k: v for k, v in params.items()},
                    "error": str(exc),
                })

        if best_policy is None:
            raise RuntimeError(f"Etapa {stage_name}: nenhuma combinação produziu resultado válido")

        return best_policy, best_params, history

    def _build_policy(
        self,
        base_policy: EquipmentPolicy,
        params: Dict[str, Any],
        zones: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> EquipmentPolicy:
        """Constrói EquipmentPolicy a partir dos parâmetros do grid."""
        from src.domain.body_zones import get_zone, resolve_zone

        # Extrai parâmetros de associação
        assoc = {
            "weight_overlap": params.get("weight_overlap", base_policy.association.weight_overlap),
            "weight_proximity": params.get("weight_proximity", base_policy.association.weight_proximity),
            "weight_ground": params.get("weight_ground", base_policy.association.weight_ground),
            "expand_x": params.get("expand_x", base_policy.association.expand_x),
            "expand_y": params.get("expand_y", base_policy.association.expand_y),
            "proximity_sigma_u": params.get("proximity_sigma_u", base_policy.association.proximity_sigma_u),
            "proximity_tolerance_v": params.get("proximity_tolerance_v", base_policy.association.proximity_tolerance_v),
            "ground_radius_m": params.get("ground_radius_m", base_policy.association.ground_radius_m),
            "use_ground": params.get("use_ground", base_policy.association.use_ground),
        }

        # Extrai parâmetros de confiança
        conf = {
            "correct_threshold": params.get("correct_threshold", base_policy.confidence.correct_threshold),
            "predicted_factor": params.get("predicted_factor", base_policy.confidence.predicted_factor),
            "unknown_state_factor": params.get("unknown_state_factor", base_policy.confidence.unknown_state_factor),
            "absence_base": params.get("absence_base", base_policy.confidence.absence_base),
            "absence_max": params.get("absence_max", base_policy.confidence.absence_max),
            "absence_candidate_penalty": params.get("absence_candidate_penalty", base_policy.confidence.absence_candidate_penalty),
            "max_confidence": params.get("max_confidence", base_policy.confidence.max_confidence),
        }

        # Extrai parâmetros de calibração
        calib = {
            "max_reprojection_rms_cm": params.get("max_reprojection_rms_cm", base_policy.calibration.max_reprojection_rms_cm),
            "min_holdout_points": params.get("min_holdout_points", base_policy.calibration.min_holdout_points),
        }

        # Constrói política
        policy_dict = {
            "policy_id": base_policy.policy_id,
            "version": base_policy.version,
            "person_classes": list(base_policy.person_classes),
            "equipment": [
                {
                    "class": rule.canonical_class,
                    "zone": rule.zone.value,
                    "required": rule.required,
                    "min_association": rule.min_association,
                    "aliases": list(rule.aliases),
                }
                for rule in base_policy.rules.values()
            ],
            "association": assoc,
            "confidence": conf,
            "calibration": calib,
        }

        # Aplica zonas calibradas (se fornecido)
        if zones:
            policy_dict["zones"] = {}
            for zone_name, zone_params in zones.items():
                zone = resolve_zone(zone_name)
                default_geom = get_zone(zone)
                policy_dict["zones"][zone_name] = {
                    "u_min": params.get(f"zone_{zone_name}_u_min", default_geom.u_min),
                    "u_max": params.get(f"zone_{zone_name}_u_max", default_geom.u_max),
                    "v_min": params.get(f"zone_{zone_name}_v_min", default_geom.v_min),
                    "v_max": params.get(f"zone_{zone_name}_v_max", default_geom.v_max),
                    "tolerance_u": params.get(f"zone_{zone_name}_tolerance_u", default_geom.tolerance_u),
                    "tolerance_v": params.get(f"zone_{zone_name}_tolerance_v", default_geom.tolerance_v),
                }

        return EquipmentPolicy.from_dict(policy_dict)

    def _evaluate_policy(
        self,
        policy: EquipmentPolicy,
        dataset: List[AnnotatedFrame],
    ) -> float:
        """Avalia uma política sobre o dataset e retorna F1 macro."""
        pairing = PairingModule(policy=policy)
        inference = RelationInferenceModule(policy=policy)

        predictions: List[RelationalEvent] = []
        for frame in dataset:
            tracking_frame = frame.to_tracking_frame()
            pairing_result = pairing.pair(tracking_frame)
            evaluations = inference.infer(pairing_result)

            event = RelationalEvent(
                camera_id=tracking_frame.camera_id,
                session_id=tracking_frame.session_id,
                frame=tracking_frame.frame,
                captured_at=tracking_frame.captured_at,
                frame_width=tracking_frame.frame_width,
                frame_height=tracking_frame.frame_height,
                calibration=None,  # type: ignore
                policy_id=policy.policy_id,
                policy_version=policy.version,
                relations=tuple(evaluations),
                unassociated_equipment=tuple(pairing_result.unassociated_equipment),
                ignored_tracks=tuple(pairing_result.ignored_tracks),
            )
            predictions.append(event)

        result = self.evaluator.evaluate(predictions, dataset)
        return result.f1_macro

    @staticmethod
    def _assoc_param_names() -> set:
        return {
            "weight_overlap", "weight_proximity", "weight_ground",
            "expand_x", "expand_y", "proximity_sigma_u", "proximity_tolerance_v",
            "ground_radius_m", "use_ground",
        }

    @staticmethod
    def _conf_param_names() -> set:
        return {
            "correct_threshold", "predicted_factor", "unknown_state_factor",
            "absence_base", "absence_max", "absence_candidate_penalty", "max_confidence",
        }
