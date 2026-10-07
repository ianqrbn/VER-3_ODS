"""
Primitivas geométricas do I9.

Somente conta encoixa de bounding boxes e transformações homogêneas; não há
nenhuma dependência de visão computacional ou de modelo. A origem das caixas é o
canto inferior esquerdo da imagem e `x_max`/`y_max` são exclusivos.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence, Tuple

from src.domain.body_zones import ZoneGeometry
from src.domain.models import BoundingBox


def normalized_position(track_bbox: BoundingBox, person_bbox: BoundingBox) -> Tuple[float, float]:
    """Converte um ponto para o sistema normalizado da bounding box da pessoa.

    `u` varia de 0 (borda esquerda) a 1 (borda direita) e `v` de 0 (base) a 1
    (topo). Valores fora do intervalo indicam que o objeto está fora da pessoa,
    o que é perfeitamente válido (capacete pode ultrapassar o topo da caixa).
    """
    u = (track_bbox.center_x - person_bbox.x_min) / person_bbox.width
    v = (track_bbox.center_y - person_bbox.y_min) / person_bbox.height
    return (u, v)


def gaussian_proximity(distance: float, sigma: float) -> float:
    """Score em [0, 1] que decai suavemente com a distância."""
    if sigma <= 0:
        return 1.0 if distance == 0 else 0.0
    return math.exp(-((distance / sigma) ** 2) / 2.0)


def person_relative_proximity(
    u: float, v: float, sigma_u: float, tolerance_v: float
) -> float:
    """Proximidade do EPI em relação à pessoa, já em coordenadas normalizadas.

    A avaliação é feita em duas dimensões independentes para não punir EPI que
    ficam no alto do corpo (capacete na cabeça, colete no tronco):

    * horizontal: gaussiana em torno do centro da pessoa, com sigma em frações
      da largura (`u = 0.5` é o centro);
    * vertical: 1.0 enquanto o centro do EPI estiver na faixa da pessoa
      (`v` entre 0 e 1), com tolerância acima da cabeça e abaixo dos pés.
    """
    horizontal = gaussian_proximity(abs(u - 0.5), sigma_u)
    gap = max(0.0, v - 1.0, -v)
    if tolerance_v > 0:
        vertical = max(0.0, 1.0 - gap / tolerance_v)
    else:
        vertical = 1.0 if gap == 0 else 0.0
    return horizontal * vertical


def zone_score(u: float, v: float, zone: ZoneGeometry) -> float:
    """Score de posicionamento em [0, 1] para a zona esperada de um EPI.

    Dentro da zona o score varia de 0.70 (na borda) a 1.00 (no centro); fora da
    zona decai linearmente até zero, ao longo da tolerância da zona. O decaimento
    é isotrópico nas tolerâncias, evitando "degraus" entre eixos.
    """
    du = max(zone.u_min - u, 0.0, u - zone.u_max)
    dv = max(zone.v_min - v, 0.0, v - zone.v_max)

    if du == 0.0 and dv == 0.0:
        margin = min(u - zone.u_min, zone.u_max - u, v - zone.v_min, zone.v_max - v)
        half_span = min((zone.u_max - zone.u_min) / 2.0, (zone.v_max - zone.v_min) / 2.0)
        interior = min(1.0, margin / half_span) if half_span > 0 else 1.0
        return 0.70 + 0.30 * interior

    normalized = math.hypot(du / zone.tolerance_u, dv / zone.tolerance_v)
    return 0.70 * max(0.0, 1.0 - normalized)


def overlap_score(candidate: BoundingBox, person: BoundingBox, expand_x: float, expand_y: float) -> float:
    """Contenção da bbox do EPI dentro da pessoa (com pequena expansão)."""
    area = person.expanded(expand_x, expand_y).containment(candidate)
    iou = person.iou(candidate)
    return max(area, iou)


def apply_homography(
    matrix: Sequence[Sequence[float]], point: Tuple[float, float]
) -> Tuple[float, float]:
    """Projeta um ponto da imagem no referencial do ambiente (row-major, 3x3)."""
    x, y = point
    h = matrix
    w = h[2][0] * x + h[2][1] * y + h[2][2]
    if w == 0:
        raise ValueError("homografia degenerada: denominador zero")
    px = (h[0][0] * x + h[0][1] * y + h[0][2]) / w
    py = (h[1][0] * x + h[1][1] * y + h[1][2]) / w
    return (px, py)


def ground_distance_m(
    matrix: Optional[Sequence[Sequence[float]]],
    point_a: Tuple[float, float],
    point_b: Tuple[float, float],
    meters_per_unit: float,
) -> Optional[float]:
    """Distância métrica entre dois pontos da imagem, ou None sem calibração."""
    if matrix is None:
        return None
    a = apply_homography(matrix, point_a)
    b = apply_homography(matrix, point_b)
    return math.hypot(a[0] - b[0], a[1] - b[1]) * meters_per_unit
