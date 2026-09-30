"""
Componente I9 — verificação geométrica de uso de EPI.

Fluxo: evento de rastreio (I2) -> associação pessoa/EPI -> estado relacional
(CORRETO / INCORRETO / AUSENTE) com confiança -> evento publicado (I9).
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


def main() -> None:
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
