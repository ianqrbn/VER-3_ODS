"""
Script de otimização do pipeline I9 usando PSO.

Uso:
    python3 optimize.py --dataset "PPE detection f.v9i.coco" --split valid --output policy_optimized.json

Carrega dataset de validação, executa PSO para maximizar F1-Macro e salva política otimizada.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.adapters.coco_dataset_adapter import CocoDatasetAdapter
from src.core.evaluation import EvaluationModule
from src.core.fitness import FitnessFunction
from src.core.inference import RelationInferenceModule
from src.core.parameters import ParameterVector
from src.core.pairing import PairingModule
from src.core.pso import PSO
from src.domain.policy import EquipmentPolicy


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Otimiza pipeline I9 usando PSO (maximiza F1-Macro)"
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Caminho para o diretório do dataset COCO",
    )
    parser.add_argument(
        "--split",
        default="valid",
        help="Split do dataset a usar para otimização (padrão: valid)",
    )
    parser.add_argument(
        "--output",
        default="policy_optimized.json",
        help="Caminho para o policy.json otimizado (padrão: policy_optimized.json)",
    )
    parser.add_argument(
        "--policy",
        default="config/policy.json",
        help="Caminho para o policy.json base (padrão: config/policy.json)",
    )
    parser.add_argument(
        "--particles",
        type=int,
        default=30,
        help="Número de partículas do PSO (padrão: 30)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help="Número de iterações do PSO (padrão: 100)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Número de workers paralelos (padrão: 4)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=500,
        help="Número máximo de frames para otimização (padrão: 500)",
    )
    args = parser.parse_args()

    # Carrega política base
    print(f"Carregando política base: {args.policy}")
    policy_base = EquipmentPolicy.from_file(args.policy)

    # Carrega dataset de validação
    print(f"Carregando dataset: {args.dataset} (split: {args.split})")
    adapter = CocoDatasetAdapter()
    dataset = adapter.load(args.dataset, split=args.split)
    print(f"  {len(dataset)} frame(s) carregado(s)")

    # Subamostra se necessário
    if len(dataset) > args.max_frames:
        step = len(dataset) / args.max_frames
        dataset = [dataset[int(i * step)] for i in range(args.max_frames)]
        print(f"  Subamostrado para {len(dataset)} frame(s)")

    # Cria função de aptidão
    print("Criando função de aptidão...")
    fitness_fn = FitnessFunction(dataset, policy_base, is_coco=True)

    # Define bounds do PSO
    bounds = ParameterVector.bounds()
    print(f"  {len(bounds)} dimensões de otimização")

    # Executa PSO
    print(f"\nIniciando PSO ({args.particles} partículas, {args.iterations} iterações, {args.workers} workers)...")
    pso = PSO(
        fitness_fn=fitness_fn.evaluate,
        bounds=bounds,
        n_particles=args.particles,
        n_iterations=args.iterations,
        n_workers=args.workers,
    )

    best_position, best_fitness = pso.optimize()

    # Salva resultados
    best_params = ParameterVector.from_list(best_position)
    policy_optimized = fitness_fn._build_policy(best_params)
    
    # Salva política otimizada
    policy_dict = {
        "policy_id": policy_optimized.policy_id,
        "version": policy_optimized.version,
        "person_classes": list(policy_optimized.person_classes),
        "equipment": [
            {
                "class": rule.canonical_class,
                "zone": rule.zone.value,
                "required": rule.required,
                "min_association": rule.min_association,
                "aliases": list(rule.aliases),
            }
            for rule in policy_optimized.rules.values()
        ],
        "association": {
            "radial_sigma": policy_optimized.association.radial_sigma,
            "weight_overlap": policy_optimized.association.weight_overlap,
            "weight_proximity": policy_optimized.association.weight_proximity,
            "weight_ground": policy_optimized.association.weight_ground,
            "expand_x": policy_optimized.association.expand_x,
            "expand_y": policy_optimized.association.expand_y,
            "proximity_sigma_u": policy_optimized.association.proximity_sigma_u,
            "proximity_tolerance_v": policy_optimized.association.proximity_tolerance_v,
            "ground_radius_m": policy_optimized.association.ground_radius_m,
            "use_ground": policy_optimized.association.use_ground,
        },
        "confidence": {
            "correct_threshold": policy_optimized.confidence.correct_threshold,
            "predicted_factor": policy_optimized.confidence.predicted_factor,
            "unknown_state_factor": policy_optimized.confidence.unknown_state_factor,
            "absence_base": policy_optimized.confidence.absence_base,
            "absence_max": policy_optimized.confidence.absence_max,
            "absence_candidate_penalty": policy_optimized.confidence.absence_candidate_penalty,
            "max_confidence": policy_optimized.confidence.max_confidence,
        },
        "calibration": {
            "max_reprojection_rms_cm": policy_optimized.calibration.max_reprojection_rms_cm,
            "min_holdout_points": policy_optimized.calibration.min_holdout_points,
        },
        "zones": {
            "HEAD": {
                "u_min": best_params.head_u_min,
                "u_max": best_params.head_u_max,
                "v_min": best_params.head_v_min,
                "v_max": best_params.head_v_max,
                "tolerance_u": 0.18,
                "tolerance_v": 0.18,
            },
            "TORSO": {
                "u_min": best_params.torso_u_min,
                "u_max": best_params.torso_u_max,
                "v_min": best_params.torso_v_min,
                "v_max": best_params.torso_v_max,
                "tolerance_u": 0.20,
                "tolerance_v": 0.16,
            },
        },
    }

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(policy_dict, handle, ensure_ascii=False, indent=2)

    # Salva relatório de otimização com métricas completas
    # Primeiro, avalia a política otimizada no dataset de validação completo
    print("\nAvaliando política otimizada no dataset de validação...")
    policy_optimized = fitness_fn._build_policy(best_params)
    
    # Carrega dataset completo (sem subamostragem) para avaliação final
    dataset_full = adapter.load(args.dataset, args.split)
    if len(dataset_full) > args.max_frames:
        step = len(dataset_full) / args.max_frames
        dataset_full = [dataset_full[int(i * step)] for i in range(args.max_frames)]
    
    predictions_full = fitness_fn._run_pipeline(policy_optimized)
    # Nota: _run_pipeline usa self.dataset, então precisamos avaliar com o dataset correto
    # Vamos usar o dataset subamostrado que foi usado na otimização
    evaluator = EvaluationModule(policy_optimized, is_coco=True)
    
    # Roda pipeline no dataset completo para métricas finais
    pairing = PairingModule(policy=policy_optimized)
    inference = RelationInferenceModule(policy=policy_optimized)
    predictions_eval = []
    for frame in dataset_full:
        tracking_frame = frame.to_tracking_frame()
        pairing_result = pairing.pair(tracking_frame)
        evaluations = inference.infer(pairing_result)
        from src.domain.models import RelationalEvent
        event = RelationalEvent(
            camera_id=tracking_frame.camera_id,
            session_id=tracking_frame.session_id,
            frame=tracking_frame.frame,
            captured_at=tracking_frame.captured_at,
            frame_width=tracking_frame.frame_width,
            frame_height=tracking_frame.frame_height,
            calibration=None,
            policy_id=policy_optimized.policy_id,
            policy_version=policy_optimized.version,
            relations=tuple(evaluations),
            unassociated_equipment=tuple(pairing_result.unassociated_equipment),
            ignored_tracks=tuple(pairing_result.ignored_tracks),
        )
        predictions_eval.append(event)
    
    eval_result = evaluator.evaluate(predictions_eval, dataset_full)

    report = {
        "optimization": {
            "algorithm": "PSO",
            "best_f1_macro": best_fitness,
            "pso_config": {
                "n_particles": args.particles,
                "n_iterations": args.iterations,
                "n_workers": args.workers,
            },
            "dataset": {
                "path": args.dataset,
                "split": args.split,
                "n_frames": len(dataset),
            },
        },
        "best_params": {
            "min_association": best_params.min_association,
            "correct_threshold": best_params.correct_threshold,
            "head_u_min": best_params.head_u_min,
            "head_u_max": best_params.head_u_max,
            "head_v_min": best_params.head_v_min,
            "head_v_max": best_params.head_v_max,
            "torso_u_min": best_params.torso_u_min,
            "torso_u_max": best_params.torso_u_max,
            "torso_v_min": best_params.torso_v_min,
            "torso_v_max": best_params.torso_v_max,
        },
        "metrics": eval_result.as_dict(),
    }

    report_path = args.output.replace(".json", "_report.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"OTIMIZAÇÃO CONCLUÍDA")
    print(f"{'='*50}")
    print(f"Melhor F1-Macro: {best_fitness:.4f}")
    print(f"Política salva: {args.output}")
    print(f"Relatório salvo: {report_path}")
    print(f"\nMelhores parâmetros:")
    print(f"  min_association: {best_params.min_association:.4f}")
    print(f"  correct_threshold: {best_params.correct_threshold:.4f}")
    print(f"  HEAD: u=[{best_params.head_u_min:.2f}, {best_params.head_u_max:.2f}], v=[{best_params.head_v_min:.2f}, {best_params.head_v_max:.2f}]")
    print(f"  TORSO: u=[{best_params.torso_u_min:.2f}, {best_params.torso_u_max:.2f}], v=[{best_params.torso_v_min:.2f}, {best_params.torso_v_max:.2f}]")


if __name__ == "__main__":
    main()
