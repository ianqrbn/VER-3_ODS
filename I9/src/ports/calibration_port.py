from typing import Optional, Protocol

from src.domain.models import Calibration


class CalibrationPort(Protocol):
    """
    Protocolo de consumo dos eventos de calibração (I3 / `ods.inferencia.calibracao`).

    Retorna a calibração mais recente conhecida para a câmera. O `CalibrationStore`
    do core decide se ela é aceita, com base nos critérios de qualidade da política.
    """

    def get_calibration(self, camera_id: str) -> Optional[Calibration]:
        ...
