"""
Script de avaliação do pipeline I9 contra dataset COCO.

Uso:
    python3 evaluate.py --policy policy_calibrated.json --split test --dataset "PPE detection f.v9i.coco"

Carrega uma política, roda o pipeline sobre um split do dataset e calcula métricas.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.adapters.coco_dataset_adapter import CocoDatasetAdapter
from src.core.evaluation import EvaluationModule
from src.core.inference import RelationInferenceModule
from src.core.pairing import PairingModule
from src.domain.models import RelationalEvent
from src.domain.policy import EquipmentPolicy


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Avalia pipeline I9 contra dataset COCO"
    )
    parser.add_argument(
        "--policy",
        required=True,
        help="Caminho para o policy.json a avaliar",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Caminho para o diretório do dataset COCO",
    )
    parser.add_argument(
        "--split",
        default="test",
        help="Split do dataset a avaliar (padrão: test)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=500,
        help="Número máximo de frames a avaliar (padrão: 500)",
    )
    args = parser.parse_args()

    # Carrega política
    print(f"Carregando política: {args.policy}")
    policy = EquipmentPolicy.from_file(args.policy)

    # Carrega dataset
    print(f"Carregando dataset: {args.dataset} (split: {args.split})")
    adapter = CocoDatasetAdapter()
    dataset = adapter.load(args.dataset, split=args.split)
    print(f"  {len(dataset)} frame(s) carregado(s)")

    # Subamostra se necessário
    if len(dataset) > args.max_frames:
        step = len(dataset) / args.max_frames
        dataset = [dataset[int(i * step)] for i in range(args.max_frames)]
        print(f"  Subamostrado para {len(dataset)} frame(s)")

    # Cria módulos
    pairing = PairingModule(policy=policy)
    inference = RelationInferenceModule(policy=policy)
    evaluator = EvaluationModule(policy, is_coco=True)

    # Roda pipeline sobre dataset
    print("Rodando pipeline...")
    predictions = []
    for i, frame in enumerate(dataset):
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(dataset)}")
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

    # Avalia
    print("Calculando métricas...")
    result = evaluator.evaluate(predictions, dataset)

    print(f"\n{'='*50}")
    print(f"RESULTADOS (split: {args.split})")
    print(f"{'='*50}")
    print(f"F1 macro: {result.f1_macro:.4f}")
    print(f"Accuracy: {result.accuracy:.4f}")
    print(f"Total predições: {result.total_predictions}")
    print(f"Total ground truth: {result.total_ground_truth}")
    print()
    print("Métricas por classe:")
    for state, metrics in result.per_class.items():
        print(f"  {state.value}:")
        print(f"    Precision: {metrics.precision:.4f}")
        print(f"    Recall:    {metrics.recall:.4f}")
        print(f"    F1:        {metrics.f1:.4f}")
        print(f"    Support:   {metrics.true_positives + metrics.false_negatives}")
    print()
    print("Matriz de confusão:")
    for (actual, predicted), count in sorted(result.confusion_matrix.items()):
        print(f"  {actual.value} -> {predicted.value}: {count}")


if __name__ == "__main__":
    main()
