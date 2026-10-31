"""
Componente I9 — verificação geométrica de uso de EPI.

Fluxo (arquitetura 6c): detecções do I1 (`ods.i1.detections`) + calibração do
I3 (`ods.i3.calibration`) -> associação pessoa/EPI -> estado relacional
(CORRETO / INCORRETO / AUSENTE) com confiança -> `ods.i9.ppe_compliance` (S2, A5).

Modos de execução:
    python3 main.py                          # modo normal (mock)
    python3 main.py --input examples/i1_detections.json   # mensagens reais do I1 (JSON ou JSONL)
    python3 main.py --kafka                  # serviço contínuo no barramento B3 (Kafka)
    python3 main.py --catalog examples/a5_ppe_catalog.json  # usa o PPE_CATALOG do A5
    python3 main.py --calibrate --format csv --dataset dataset.csv  # calibração CSV
    python3 main.py --calibrate --format coco --dataset "PPE detection.f.v9i.coco"  # calibração COCO
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.adapters.message_adapters import (  # noqa: E402
    MessageCalibrationAdapter,
    MessageIngestionAdapter,
)
from src.adapters.mock_adapters import (  # noqa: E402
    MockCalibrationAdapter,
    MockConsoleOutputAdapter,
    MockIngestionAdapter,
)
from src.core.calibration import CalibrationStore  # noqa: E402
from src.core.inference import RelationInferenceModule  # noqa: E402
from src.core.pairing import PairingModule  # noqa: E402
from src.core.pipeline import I9Pipeline  # noqa: E402
from src.domain.catalog import PpeCatalog  # noqa: E402
from src.domain.policy import EquipmentPolicy  # noqa: E402

POLICY_PATH = Path(__file__).resolve().parent / "config" / "policy.json"


def read_messages(path: str) -> list:
    """Lê mensagens de um arquivo: um objeto JSON, uma lista JSON ou JSONL."""
    import json

    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return data if isinstance(data, list) else [data]


def build_pipeline(
    max_frames: int = 3,
    as_json: bool = False,
    input_path: str | None = None,
    calibration_path: str | None = None,
    ingestion=None,
    calibration=None,
    output=None,
    catalog_path: str | None = None,
) -> I9Pipeline:
    policy = EquipmentPolicy.from_file(POLICY_PATH)
    calibration_store = CalibrationStore(policy.calibration)

    # Dependências injetadas (DIP): adaptadores passados explicitamente (ex.: Kafka)
    # têm precedência; senão, arquivo de mensagens ou mock.
    if ingestion is None and input_path:
        ingestion = MessageIngestionAdapter(read_messages(input_path))
        calibration = calibration or MessageCalibrationAdapter(
            read_messages(calibration_path) if calibration_path else ()
        )
    ingestion = ingestion or MockIngestionAdapter(max_frames=max_frames)
    calibration = calibration or MockCalibrationAdapter()
    output = output or MockConsoleOutputAdapter(as_json=as_json)

    pairing = PairingModule(policy=policy, calibration_store=calibration_store)
    inference = RelationInferenceModule(policy=policy)

    pipeline = I9Pipeline(
        ingestion_port=ingestion,
        output_port=output,
        calibration_port=calibration,
        pairing_module=pairing,
        inference_module=inference,
        policy=policy,
    )
    if catalog_path:
        # conteúdo do PPE_CATALOG como o A5 serve no registro
        content = read_messages(catalog_path)[0]
        pipeline.apply_catalog(PpeCatalog.from_content(content, artifact_version=Path(catalog_path).stem))
    return pipeline


def run_kafka() -> None:
    """Serviço contínuo: ods.i1.detections + ods.i3.calibration -> ods.i9.ppe_compliance."""
    import logging

    from src.adapters.kafka_adapters import (
        KafkaSettings,
        build_kafka_service,
        install_signal_handlers,
    )

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = KafkaSettings.from_env()
    logging.getLogger("i9.kafka").info(
        "conectando em %s (grupo %s): %s + %s -> %s",
        settings.bootstrap_servers, settings.group_id, settings.detections_topic,
        settings.calibration_topic, settings.compliance_topic,
    )
    service = build_kafka_service(build_pipeline, settings)
    install_signal_handlers(service)
    processados = service.run(warmup_s=settings.calibration_warmup_s)
    logging.getLogger("i9.kafka").info("encerrado: %d quadro(s) processado(s)", processados)


def run_calibration(
    dataset_path: str,
    output_path: str = "policy_calibrated.json",
    format: str = "csv",
    split: str = "train",
    max_frames: int = 200,
) -> None:
    """Executa calibração das regras geométricas usando dataset annotado."""
    from src.adapters.csv_dataset_adapter import CsvDatasetAdapter
    from src.adapters.coco_dataset_adapter import CocoDatasetAdapter
    from src.core.rule_calibration import RuleCalibrationModule

    # Carrega política base
    print(f"Carregando política base: {POLICY_PATH}")
    base_policy = EquipmentPolicy.from_file(POLICY_PATH)

    # Carrega dataset
    print(f"Carregando dataset: {dataset_path} (formato: {format})")
    if format == "coco":
        adapter = CocoDatasetAdapter()
        dataset = adapter.load(dataset_path, split=split)
        is_coco = True
    else:
        adapter = CsvDatasetAdapter()
        dataset = adapter.load(dataset_path)
        is_coco = False
    print(f"  {len(dataset)} frame(s) carregado(s)")

    # Subamostra se necessário (para viabilidade em datasets grandes)
    if len(dataset) > max_frames:
        step = len(dataset) / max_frames
        dataset = [dataset[int(i * step)] for i in range(max_frames)]
        print(f"  Subamostrado para {len(dataset)} frame(s) para calibração")

    # Define grid de parâmetros
    param_grid = {
        "correct_threshold": [0.70, 0.75, 0.80],
        "weight_overlap": [0.5, 0.6, 0.7],
        "weight_proximity": [0.3, 0.4, 0.5],
        "proximity_sigma_u": [0.4, 0.5, 0.6],
        "proximity_tolerance_v": [0.20, 0.25, 0.30],
        "absence_base": [0.55, 0.62, 0.70],
    }

    zones = {
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

    # Executa calibração
    print(f"Iniciando calibração com {len(param_grid)} parâmetros...")
    calibrator = RuleCalibrationModule(base_policy, is_coco=is_coco)
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
        "--kafka",
        action="store_true",
        help="Roda como serviço contínuo no Kafka (configuração por variáveis de ambiente)",
    )
    parser.add_argument(
        "--input",
        help="Arquivo com mensagens ods.i1.detections (JSON ou JSONL) no lugar do mock",
    )
    parser.add_argument(
        "--calibration",
        help="Arquivo com mensagens ods.i3.calibration (JSON ou JSONL), usado com --input",
    )
    parser.add_argument(
        "--catalog",
        help="Arquivo com o conteúdo do PPE_CATALOG do A5 (no lugar da lista local de EPIs)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime o evento ods.i9.ppe_compliance completo em JSON",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Executa modo de calibração com dataset annotado",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "coco"],
        default="csv",
        help="Formato do dataset (padrão: csv)",
    )
    parser.add_argument(
        "--split",
        default="train",
        help="Split do dataset COCO a carregar (padrão: train)",
    )
    parser.add_argument(
        "--dataset",
        help="Caminho para o dataset (obrigatório com --calibrate)",
    )
    parser.add_argument(
        "--output",
        default="policy_calibrated.json",
        help="Caminho para o policy.json calibrado (padrão: policy_calibrated.json)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=200,
        help="Número máximo de frames para calibração (padrão: 200)",
    )
    args = parser.parse_args()

    if args.calibrate:
        if not args.dataset:
            parser.error("--calibrate requer --dataset")
        run_calibration(args.dataset, args.output, format=args.format, split=args.split, max_frames=args.max_frames)
        return

    if args.kafka:
        run_kafka()
        return

    print("Iniciando Componente I9 (verificação geométrica)...")

    pipeline = build_pipeline(
        as_json=args.json,
        input_path=args.input,
        calibration_path=args.calibration,
        catalog_path=args.catalog,
    )
    processados = 0
    while True:
        if pipeline.run_once() is None:
            break
        processados += 1

    print(f"\nProcessamento concluído: {processados} quadro(s) verificado(s).")


if __name__ == "__main__":
    main()
