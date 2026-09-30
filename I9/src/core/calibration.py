"""
Repositório em memória das calibrações recebidas do I3.

O I9 não calcula homografia: ele consome a matriz publicada pelo I3, valida os
indicadores de qualidade e mantém, por câmera, a versão válida mais recente.
"""

from __future__ import annotations

from typing import Dict, Optional

from src.domain.models import Calibration, CalibrationStatus
from src.domain.policy import CalibrationSettings


class CalibrationStore:
    def __init__(self, settings: Optional[CalibrationSettings] = None):
        self._settings = settings or CalibrationSettings()
        self._by_camera: Dict[str, Calibration] = {}
        self._rejected: Dict[str, str] = {}

    def upsert(self, calibration: Calibration) -> bool:
        """Registra a calibração se passar nos critérios de qualidade.

        Retorna True quando a calibração foi aceita. Uma calibração inválida não
        substitui uma versão boa anterior, apenas fica registrada como rejeitada.
        """
        reason = self._validate(calibration)
        if reason is not None:
            self._rejected[calibration.camera_id] = reason
            return False

        atual = self._by_camera.get(calibration.camera_id)
        if atual is None or atual.calibration_version == calibration.calibration_version:
            self._by_camera[calibration.camera_id] = calibration
        else:
            # mantém a versão já aceita: a troca deve ser explícita pelo consumidor
            self._rejected[calibration.camera_id] = (
                f"calibração {calibration.calibration_version!r} recebida com "
                f"{atual.calibration_version!r} já ativa; reinicie o consumidor para trocar"
            )
        return True

    def get(self, camera_id: str) -> Optional[Calibration]:
        return self._by_camera.get(camera_id)

    def status(self, camera_id: str) -> CalibrationStatus:
        calibration = self._by_camera.get(camera_id)
        if calibration is None:
            return CalibrationStatus(
                version=None,
                status="rejected" if camera_id in self._rejected else "missing",
                reason=self._rejected.get(camera_id),
            )
        return CalibrationStatus(version=calibration.calibration_version, status="valid")

    def _validate(self, calibration: Calibration) -> Optional[str]:
        rms = calibration.reprojection_rms_cm
        if rms is not None and rms > self._settings.max_reprojection_rms_cm:
            return (
                f"reprojection_rms_cm={rms} acima do limite "
                f"{self._settings.max_reprojection_rms_cm}"
            )
        holdout = calibration.holdout_points
        if holdout is not None and holdout < self._settings.min_holdout_points:
            return (
                f"holdout_points={holdout} abaixo do mínimo "
                f"{self._settings.min_holdout_points}"
            )
        return None
