"""
Função de aptidão para otimização do pipeline I9.

Avalia um vetor de parâmetros e retorna o F1-Macro obtido no dataset de validação.
"""

from __future__ import annotations

from typing import List

from src.core.evaluation import EvaluationModule
from src.core.inference import RelationInferenceModule
from src.core.pairing import PairingModule
from src.core.parameters import ParameterVector
from src.domain.models import AnnotatedFrame, RelationalEvent
from src.domain.policy import EquipmentPolicy


class FitnessFunction:
    """Função de aptidão para PSO: maximiza F1-Macro."""
    
    def __init__(
        self,
        dataset: List[AnnotatedFrame],
        policy_base: EquipmentPolicy,
        is_coco: bool = True,
    ):
        self.dataset = dataset
        self.policy_base = policy_base
        self.is_coco = is_coco
    
    def evaluate(self, params_vector) -> float:
        """Avalia um vetor de parâmetros e retorna F1-Macro.
        
        Args:
            params_vector: ParameterVector ou lista de floats
            
        Returns:
            F1-Macro obtido no dataset de validação
        """
        # Aceita tanto ParameterVector quanto lista de floats
        if isinstance(params_vector, list):
            params_vector = ParameterVector.from_list(params_vector)
        
        # 1. Constrói política com os parâmetros
        policy = self._build_policy(params_vector)
        
        # 2. Roda pipeline sobre dataset
        predictions = self._run_pipeline(policy)
        
        # 3. Calcula métricas
        evaluator = EvaluationModule(policy, is_coco=self.is_coco)
        result = evaluator.evaluate(predictions, self.dataset)
        
        return result.f1_macro
    
    def _build_policy(self, params: ParameterVector) -> EquipmentPolicy:
        """Constrói EquipmentPolicy a partir do vetor de parâmetros."""
        from src.domain.body_zones import BodyZone, ZoneGeometry
        
        # Constrói zonas customizadas
        custom_zones = {
            BodyZone.HEAD: ZoneGeometry(
                u_min=params.head_u_min,
                u_max=params.head_u_max,
                v_min=params.head_v_min,
                v_max=params.head_v_max,
                tolerance_u=0.18,
                tolerance_v=0.18,
            ),
            BodyZone.TORSO: ZoneGeometry(
                u_min=params.torso_u_min,
                u_max=params.torso_u_max,
                v_min=params.torso_v_min,
                v_max=params.torso_v_max,
                tolerance_u=0.20,
                tolerance_v=0.16,
            ),
        }
        
        # Constrói política
        policy_dict = {
            "policy_id": self.policy_base.policy_id,
            "version": self.policy_base.version,
            "person_classes": list(self.policy_base.person_classes),
            "equipment": [
                {
                    "class": rule.canonical_class,
                    "zone": rule.zone.value,
                    "required": rule.required,
                    "min_association": params.min_association,
                    "aliases": list(rule.aliases),
                }
                for rule in self.policy_base.rules.values()
            ],
            "association": {
                "radial_sigma": self.policy_base.association.radial_sigma,
                "weight_overlap": self.policy_base.association.weight_overlap,
                "weight_proximity": self.policy_base.association.weight_proximity,
                "weight_ground": self.policy_base.association.weight_ground,
                "expand_x": self.policy_base.association.expand_x,
                "expand_y": self.policy_base.association.expand_y,
                "proximity_sigma_u": self.policy_base.association.proximity_sigma_u,
                "proximity_tolerance_v": self.policy_base.association.proximity_tolerance_v,
                "ground_radius_m": self.policy_base.association.ground_radius_m,
                "use_ground": self.policy_base.association.use_ground,
            },
            "confidence": {
                "correct_threshold": params.correct_threshold,
                "predicted_factor": self.policy_base.confidence.predicted_factor,
                "unknown_state_factor": self.policy_base.confidence.unknown_state_factor,
                "absence_base": self.policy_base.confidence.absence_base,
                "absence_max": self.policy_base.confidence.absence_max,
                "absence_candidate_penalty": self.policy_base.confidence.absence_candidate_penalty,
                "max_confidence": self.policy_base.confidence.max_confidence,
            },
            "calibration": {
                "max_reprojection_rms_cm": self.policy_base.calibration.max_reprojection_rms_cm,
                "min_holdout_points": self.policy_base.calibration.min_holdout_points,
            },
            "zones": {
                "HEAD": {
                    "u_min": params.head_u_min,
                    "u_max": params.head_u_max,
                    "v_min": params.head_v_min,
                    "v_max": params.head_v_max,
                    "tolerance_u": 0.18,
                    "tolerance_v": 0.18,
                },
                "TORSO": {
                    "u_min": params.torso_u_min,
                    "u_max": params.torso_u_max,
                    "v_min": params.torso_v_min,
                    "v_max": params.torso_v_max,
                    "tolerance_u": 0.20,
                    "tolerance_v": 0.16,
                },
            },
        }
        
        return EquipmentPolicy.from_dict(policy_dict)
    
    def _run_pipeline(self, policy: EquipmentPolicy) -> List[RelationalEvent]:
        """Roda pipeline sobre dataset e retorna predições."""
        pairing = PairingModule(policy=policy)
        inference = RelationInferenceModule(policy=policy)
        
        predictions = []
        for frame in self.dataset:
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
        
        return predictions
