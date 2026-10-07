"""
Zonas do corpo humano: conhecimento de domínio do verificador de EPI.

O I9 é um verificador **especializado em pessoas** (Opção A): a geometria de cada
região anatômica é constante do motor, e a aplicação apenas indica qual EPI deve
ser usado em cada zona. Isso mantém a configuração enxuta e concentrada no que
realmente varia por contexto: *quais* EPIs existem e *quais* são obrigatórios.

As zonas usam coordenadas **normalizadas** da bounding box da pessoa, com a origem
do I2 (canto inferior esquerdo, máximos exclusivos):

    u = (cx_epi - x_min_pessoa) / largura_pessoa    (0 = esquerda, 1 = direita)
    v = (cy_epi - y_min_pessoa) / altura_pessoa     (0 = base, 1 = topo da cabeça)

Como `v` cresce para cima, a cabeça fica próxima de `v = 1` e o quadril de `v = 0`.
O limite superior pode passar de 1.0 porque um capacete legitimamente ultrapassa o
topo da bounding box da pessoa.

Para acrescentar uma zona (por exemplo `EARS`, `FEET` ou `WAIST`):

1. adicione a constante em `BodyZone`;
2. registre a geometria em `ZONAS`;
3. cubra com teste em `tests/test_body_zones.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Tuple, Union


class BodyZone(str, Enum):
    """Regiões anatômicas reconhecidas pelo verificador."""

    HEAD = "HEAD"
    TORSO = "TORSO"
    HANDS = "HANDS"


@dataclass(frozen=True)
class ZoneGeometry:
    """Retângulo esperado de uma zona, em coordenadas normalizadas da pessoa."""

    u_min: float
    u_max: float
    v_min: float
    v_max: float
    tolerance_u: float = 0.18
    tolerance_v: float = 0.16

    def __post_init__(self) -> None:
        if self.u_max <= self.u_min or self.v_max <= self.v_min:
            raise ValueError(
                f"geometria inválida: exige max > min em ambos os eixos -> {self!r}"
            )
        if self.tolerance_u <= 0 or self.tolerance_v <= 0:
            raise ValueError(f"tolerâncias devem ser positivas -> {self!r}")

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.u_min + self.u_max) / 2.0, (self.v_min + self.v_max) / 2.0)


# Geometria padrão do corpo humano nas coordenadas do I2.
# Os números são proporções da altura da bounding box, não medidas em pixels.
ZONAS: Dict[BodyZone, ZoneGeometry] = {
    BodyZone.HEAD: ZoneGeometry(
        u_min=0.28, u_max=0.72, v_min=0.72, v_max=1.10, tolerance_u=0.18, tolerance_v=0.18
    ),
    BodyZone.TORSO: ZoneGeometry(
        u_min=0.20, u_max=0.80, v_min=0.38, v_max=0.74, tolerance_u=0.20, tolerance_v=0.16
    ),
    BodyZone.HANDS: ZoneGeometry(
        u_min=0.02, u_max=0.98, v_min=0.10, v_max=0.55, tolerance_u=0.15, tolerance_v=0.18
    ),
}

# Zonas customizáveis (injetadas via EquipmentPolicy para calibração)
_CUSTOM_ZONES: Dict[BodyZone, ZoneGeometry] = {}


def set_custom_zones(zones: Dict[BodyZone, ZoneGeometry]) -> None:
    """Define zonas customizadas (usadas durante calibração).

    Se não chamado, os valores padrão de ZONAS são usados.
    """
    _CUSTOM_ZONES.clear()
    _CUSTOM_ZONES.update(zones)


def clear_custom_zones() -> None:
    """Remove zonas customizadas, voltando aos valores padrão."""
    _CUSTOM_ZONES.clear()


def resolve_zone(nome: Union[str, BodyZone]) -> BodyZone:
    """Zona canônica a partir do nome (case-insensitive) ou do próprio enum.

    Levanta `ValueError` quando a zona não existe: uma política que aponta para
    uma região desconhecida é um erro de configuração, não um caso silencioso.
    """
    if isinstance(nome, BodyZone):
        return nome
    try:
        return BodyZone(str(nome).strip().upper())
    except ValueError as exc:
        disponiveis = ", ".join(z.value for z in BodyZone)
        raise ValueError(
            f"zona desconhecida {nome!r}; zonas disponíveis: {disponiveis}"
        ) from exc


def get_zone(nome: Union[str, BodyZone]) -> ZoneGeometry:
    """Geometria de uma zona pelo nome.

    Usa zonas customizadas se definidas via `set_custom_zones`, caso contrário
    usa os valores padrão de ZONAS.
    """
    zone = resolve_zone(nome)
    if zone in _CUSTOM_ZONES:
        return _CUSTOM_ZONES[zone]
    return ZONAS[zone]
