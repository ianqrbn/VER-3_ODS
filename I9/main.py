"""
Componente I9 — verificação geométrica de uso de EPI.

Fluxo: evento de rastreio (I3) -> associação pessoa/EPI -> estado relacional
(CORRETO / INCORRETO / AUSENTE) com confiança -> evento publicado (I9).

Modos de execução:
    python3 main.py                          # modo normal (mock)
    python3 main.py --calibrate --dataset dataset.csv  # modo calibração
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.adapters.mock_adapters import (  # noqa: E402
    MockCalibrationAdapter,
    MockConsoleOutputAdapter,
    MockIngestionAdapter,
)
from src.core.calibration import CalibrationStore  # noqa: E402
from src.core.inference import RelationInferenceModule  # noqa: E402
from src.core.pairing import PairingModule  # noqa: E402
from src.core.pipeline import I9Pipeline  # noqa: E402
from src.domain.policy import EquipmentPolicy  # noqa: E402

POLICY_PATH = Path(__file__).resolve().parent / "config" / "policy.json"


def build_pipeline(max_frames: int = 3, as_json: bool = False) -> I9Pipeline:
    policy = EquipmentPolicy.from_file(POLICY_PATH)
    calibration_store = CalibrationStore(policy.calibration)

    # Dependências injetadas (DIP): aqui entram as implementações reais pub/sub.
    ingestion = MockIngestionAdapter(max_frames=max_frames)
    calibration = MockCalibrationAdapter()
    output = MockConsoleOutputAdapter(as_json=as_json)

    pairing = PairingModule(policy=policy, calibration_store=calibration_store)
    inference = RelationInferenceModule(policy=policy)

    return I9Pipeline(
        ingestion_port=ingestion,
        output_port=output,
        calibration_port=calibration,
        pairing_module=pairing,
        inference_module=inference,
        policy=policy,
    )


def run_calibration(dataset_path: str, output_path: str = "policy_calibrated.json") -> None:
    """Executa calibração das regras geométricas usando dataset anotado."""
    from src.adapters.csv_dataset_adapter import CsvDatasetAdapter
    from src.core.rule_calibration import RuleCalibrationModule

    # Carrega política base
    print(f"Carregando política base: {POLICY_PATH}")
    base_policy = EquipmentPolicy.from_file(POLICY_PATH)

    # Carrega dataset
    print(f"Carregando dataset: {dataset_path}")
    adapter = CsvDatasetAdapter()
    dataset = adapter.load(dataset_path)
    print(f"  {len(dataset)} frame(s) carregado(s)")

    # Define grid de parâmetros
    param_grid = {
        "correct_threshold": [0.60, 0.65, 0.70, 0.75, 0.80, 0.85],
        "weight_overlap": [0.4, 0.5, 0.6, 0.7, 0.8],
        "weight_proximity": [0.2, 0.3, 0.4, 0.5, 0.6],
        "proximity_sigma_u": [0.3, 0.4, 0.5, 0.6, 0.7],
        "proximity_tolerance_v": [0.15, 0.20, 0.25, 0.30, 0.35],
        "absence_base": [0.50, 0.55, 0.62, 0.70, 0.80],
    }

    zones = {
        "HEAD": {
            "u_min": [0.20, 0.25, 0.28, 0.32, 0.35],
            "u_max": [0.65, 0.70, 0.72, 0.78, 0.80],
            "v_min": [0.65, 0.70, 0.72, 0.75, 0.80],
            "v_max": [1.00, 1.05, 1.10, 1.15],
            "tolerance_u": [0.15, 0.18, 0.20, 0.22],
            "tolerance_v": [0.15, 0.18, 0.20, 0.22],
        },
        "TORSO": {
            "u_min": [0.15, 0.20, 0.25, 0.30],
            "u_max": [0.70, 0.75, 0.80, 0.85],
            "v_min": [0.30, 0.35, 0.38, 0.42, 0.45],
            "v_max": [0.70, 0.72, 0.74, 0.78, 0.80],
            "tolerance_u": [0.15, 0.20, 0.22, 0.25],
            "tolerance_v": [0.12, 0.16, 0.18, 0.20],
        },
        "HANDS": {
            "u_min": [0.00, 0.02, 0.05, 0.10],
            "u_max": [0.90, 0.95, 0.98, 1.00],
            "v_min": [0.05, 0.10, 0.15, 0.20],
            "v_max": [0.45, 0.50, 0.55, 0.60],
            "tolerance_u": [0.10, 0.15, 0.18, 0.20],
            "tolerance_v": [0.15, 0.18, 0.20, 0.22],
        },
    }

    # Executa calibração
    print(f"Iniciando calibração com {len(param_grid)} parâmetros...")
    calibrator = RuleCalibrationModule(base_policy)
    result = calibrator.calibrate(dataset, param_grid, zones)

    # Salva resultados
    result.save_policy(output_path)
    report_path = output_path.replace(".json", "_report.json")
    result.save_report(report_path)

    print(f"\nCalibração concluída!")
    print(f"  F1 macro: {result.best_f1_macro:.4f}")
    print(f"  Política salva: {output_path}")
    print(f"  Relatório salvo: {report_path}")
    print(f"\nMelhores parâmetros:")
    for key, value in result.best_params.items():
        print(f"  {key}: {value}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Componente I9 — verificação geométrica de uso de EPI"
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Executa modo de calibração com dataset anotado",
    )
    parser.add_argument(
        "--dataset",
        help="Caminho para o CSV anotado (obrigatório com --calibrate)",
    )
    parser.add_argument(
        "--output",
        default="policy_calibrated.json",
        help="Caminho para o policy.json calibrado (padrão: policy_calibrated.json)",
    )
    args = parser.parse_args()

    if args.calibrate:
        if not args.dataset:
            parser.error("--calibrate requer --dataset")
        run_calibration(args.dataset, args.output)
        return

    print("Iniciando Componente I9 (verificação geométrica)...")

    pipeline = build_pipeline()
    processados = 0
    while True:
        if pipeline.run_once() is None:
            break
        processados += 1

    print(f"\nProcessamento concluído: {processados} quadro(s) verificado(s).")


if __name__ == "__main__":
    main()
