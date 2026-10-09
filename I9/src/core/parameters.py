"""
Vetor de parâmetros otimizáveis do pipeline I9.

Transforma os parâmetros geométricos em um vetor para otimização via PSO.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class ParameterVector:
    """Vetor de parâmetros otimizáveis.
    
    Parâmetros:
        min_association: threshold mínimo para associar EPI a pessoa
        correct_threshold: threshold para classificar como CORRETO
        head_u_min, head_u_max: limites horizontais da zona HEAD
        head_v_min, head_v_max: limites verticais da zona HEAD
        torso_u_min, torso_u_max: limites horizontais da zona TORSO
        torso_v_min, torso_v_max: limites verticais da zona TORSO
    """
    
    min_association: float = 0.45
    correct_threshold: float = 0.70
    
    # Limites da zona HEAD
    head_u_min: float = 0.28
    head_u_max: float = 0.72
    head_v_min: float = 0.72
    head_v_max: float = 1.10
    
    # Limites da zona TORSO
    torso_u_min: float = 0.20
    torso_u_max: float = 0.80
    torso_v_min: float = 0.38
    torso_v_max: float = 0.74
    
    def to_list(self) -> List[float]:
        """Converte para lista de floats."""
        return [
            self.min_association, self.correct_threshold,
            self.head_u_min, self.head_u_max, self.head_v_min, self.head_v_max,
            self.torso_u_min, self.torso_u_max, self.torso_v_min, self.torso_v_max,
        ]
    
    @classmethod
    def from_list(cls, values: List[float]) -> "ParameterVector":
        """Cria ParameterVector a partir de lista de floats."""
        if len(values) != 10:
            raise ValueError(f"Esperado 10 valores, recebido {len(values)}")
        return cls(*values)
    
    @classmethod
    def bounds(cls) -> List[Tuple[float, float]]:
        """Retorna limites (min, max) para cada parâmetro."""
        return [
            (0.30, 0.60),   # min_association
            (0.50, 0.90),   # correct_threshold
            (0.15, 0.40),   # head_u_min
            (0.60, 0.85),   # head_u_max
            (0.60, 0.85),   # head_v_min
            (0.95, 1.25),   # head_v_max
            (0.10, 0.35),   # torso_u_min
            (0.65, 0.90),   # torso_u_max
            (0.25, 0.50),   # torso_v_min
            (0.60, 0.85),   # torso_v_max
        ]
    
    @classmethod
    def default(cls) -> "ParameterVector":
        """Retorna vetor com valores padrão."""
        return cls()
