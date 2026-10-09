"""
Script standalone de calibração das regras geométricas.

Uso:
    python3 calibrate.py --format csv --dataset dataset.csv --output policy_calibrated.json
    python3 calibrate.py --format coco --dataset "PPE detection.f.v9i.coco" --output policy_calibrated.json

Fluxo:
    1. Carrega dataset (CSV ou COCO JSON)
    2. Define o grid de parâmetros
    3. Roda RuleCalibrationModule.calibrate()
    4. Salva o melhor policy.json + relatório de calibração
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.adapters.csv_dataset_adapter import CsvDatasetAdapter
from src.adapters.coco_dataset_adapter import CocoDatasetAdapter
from src.core.rule_calibration import RuleCalibrationModule
from src.domain.policy import EquipmentPolicy


# Grid padrão de parâmetros para calibração (reduzido para viabilidade)
DEFAULT_PARAM_GRID = {
    "correct_threshold": [0.70, 0.75, 0.80],
    "weight_overlap": [0.5, 0.6, 0.7],
    "weight_proximity": [0.3, 0.4, 0.5],
    "proximity_sigma_u": [0.4, 0.5, 0.6],
    "proximity_tolerance_v": [0.20, 0.25, 0.30],
    "absence_base": [0.55, 0.62, 0.70],
}

# Zonas do corpo para calibração (reduzido para viabilidade)
DEFAULT_ZONES = {
    "HEAD": {
        "u_min": [0.25, 0.28, 0.32],
        "u_max": [0.68, 0.72, 0.76],
        "v_min": [0.68, 0.72, 0.76],
        "v_max": [1.05, 1.10, 1.15],
        "tolerance_u": [0.15, 0.18],
        "tolerance_v": [0.15, 0.18],
    },
    "TORSO": {
        "u_min": [0.18, 0.20, 0.25],
        "u_max": [0.75, 0.80, 0.85],
        "v_min": [0.35, 0.38, 0.42],
        "v_max": [0.70, 0.74, 0.78],
        "tolerance_u": [0.18, 0.20],
        "tolerance_v": [0.14, 0.16],
    },
}

# Número máximo de frames para calibração (subamostragem para viabilidade)
DEFAULT_MAX_FRAMES = 200


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calibra regras geométricas do I9 usando dataset anotado"
    )
    parser.add_argument(
        "--format",
        choices=["csv", "coco"],
        default="csv",
        help="Formato do dataset (padrão: csv)",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Caminho para o dataset (CSV ou diretório COCO)",
    )
    parser.add_argument(
        "--split",
        default="train",
        help="Split do dataset COCO a carregar (padrão: train)",
    )
    parser.add_argument(
        "--output",
        default="policy_calibrated.json",
        help="Caminho para o policy.json calibrado (padrão: policy_calibrated.json)",
    )
    parser.add_argument(
        "--report",
        default="calibration_report.json",
        help="Caminho para o relatório de calibração (padrão: calibration_report.json)",
    )
    parser.add_argument(
        "--policy",
        default="config/policy.json",
        help="Caminho para o policy.json base (padrão: config/policy.json)",
    )
    parser.add_argument(
        "--grid",
        help="Caminho para JSON com grid de parâmetros customizado (opcional)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=DEFAULT_MAX_FRAMES,
        help=f"Número máximo de frames para calibração (padrão: {DEFAULT_MAX_FRAMES})",
    )
    args = parser.parse_args()

    # Carrega política base
    print(f"Carregando política base: {args.policy}")
    base_policy = EquipmentPolicy.from_file(args.policy)

    # Carrega dataset
    print(f"Carregando dataset: {args.dataset} (formato: {args.format})")
    if args.format == "coco":
        adapter = CocoDatasetAdapter()
        dataset = adapter.load(args.dataset, split=args.split)
        is_coco = True
    else:
        adapter = CsvDatasetAdapter()
        dataset = adapter.load(args.dataset)
        is_coco = False
    print(f"  {len(dataset)} frame(s) carregado(s)")

    # Subamostra se necessário (para viabilidade em datasets grandes)
    if len(dataset) > args.max_frames:
        step = len(dataset) / args.max_frames
        dataset = [dataset[int(i * step)] for i in range(args.max_frames)]
        print(f"  Subamostrado para {len(dataset)} frame(s) para calibração")

    # Define grid de parâmetros
    if args.grid:
        with open(args.grid, "r", encoding="utf-8") as handle:
            param_grid = json.load(handle)
        zones = None  # Zonas não são calibradas se grid customizado é fornecido
    else:
        param_grid = DEFAULT_PARAM_GRID
        zones = DEFAULT_ZONES

    # Executa calibração
    print(f"Iniciando calibração com {len(param_grid)} parâmetros...")
    calibrator = RuleCalibrationModule(base_policy, is_coco=is_coco)
    result = calibrator.calibrate(dataset, param_grid, zones)

    # Salva resultados
    result.save_policy(args.output)
    result.save_report(args.report)

    print(f"\nCalibração concluída!")
    print(f"  F1 macro: {result.best_f1_macro:.4f}")
    print(f"  Política salva: {args.output}")
    print(f"  Relatório salvo: {args.report}")
    print(f"\nMelhores parâmetros:")
    for key, value in result.best_params.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
