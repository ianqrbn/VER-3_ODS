"""Testes das primitivas geométricas e do modelo de bounding box."""

from __future__ import annotations

import unittest

from tests.helpers import PERSON_BOX, make_bbox
from src.core.geometry import (
    apply_homography,
    gaussian_proximity,
    ground_distance_m,
    normalized_position,
    overlap_score,
    person_relative_proximity,
    zone_score,
)
from src.domain.body_zones import ZoneGeometry, get_zone
from src.domain.models import BoundingBox


class BoundingBoxTest(unittest.TestCase):
    def test_medidas_respeitam_origem_inferior_esquerda(self):
        box = make_bbox(10, 20, 30, 40)
        self.assertEqual(box.width, 30)
        self.assertEqual(box.height, 40)
        self.assertEqual(box.center_x, 25)
        self.assertEqual(box.center_y, 40)
        self.assertEqual(box.area, 1200)

    def test_maximos_exclusivos(self):
        box = BoundingBox(0, 0, 10, 10)
        self.assertTrue(box.contains(0, 0))
        self.assertTrue(box.contains(9.999, 9.999))
        self.assertFalse(box.contains(10, 5))
        self.assertFalse(box.contains(5, 10))

    def test_bbox_invertida_e_rejeitada(self):
        with self.assertRaises(ValueError):
            BoundingBox(10, 0, 10, 10)
        with self.assertRaises(ValueError):
            BoundingBox(0, 10, 10, 10)

    def test_intersecao_iou_e_contencao(self):
        a = BoundingBox(0, 0, 10, 10)
        b = BoundingBox(5, 5, 15, 15)
        self.assertEqual(a.intersection_area(b), 25)
        self.assertAlmostEqual(a.iou(b), 25 / 175)
        self.assertAlmostEqual(a.containment(b), 25 / 100)
        self.assertEqual(a.intersection_area(BoundingBox(20, 20, 25, 25)), 0)

    def test_expansao(self):
        box = BoundingBox(0, 0, 10, 10).expanded(0.5, 0.1)
        self.assertEqual((box.x_min, box.x_max), (-5.0, 15.0))
        self.assertEqual((box.y_min, box.y_max), (-1.0, 11.0))


class NormalizedPositionTest(unittest.TestCase):
    def test_origem_no_canto_inferior_esquerdo(self):
        base = make_bbox(PERSON_BOX.x_min, PERSON_BOX.y_min, 20, 20)
        u, v = normalized_position(base, PERSON_BOX)
        self.assertAlmostEqual(u, 10 / PERSON_BOX.width)
        self.assertAlmostEqual(v, 10 / PERSON_BOX.height)

    def test_topo_da_pessoa(self):
        topo = make_bbox(PERSON_BOX.x_min, PERSON_BOX.y_max - 20, 20, 20)
        _, v = normalized_position(topo, PERSON_BOX)
        self.assertAlmostEqual(v, 1.0 - 10 / PERSON_BOX.height)

    def test_acima_do_topo_da_pessoa(self):
        acima = make_bbox(PERSON_BOX.x_min, PERSON_BOX.y_max, 20, 20)
        _, v = normalized_position(acima, PERSON_BOX)
        self.assertGreater(v, 1.0)


class ZoneScoreTest(unittest.TestCase):
    def setUp(self):
        self.zone = ZoneGeometry(
            u_min=0.30,
            u_max=0.70,
            v_min=0.72,
            v_max=1.10,
            tolerance_u=0.18,
            tolerance_v=0.18,
        )

    def test_centro_da_zona(self):
        self.assertAlmostEqual(zone_score(0.50, 0.91, self.zone), 1.0)

    def test_borda_da_zona(self):
        self.assertAlmostEqual(zone_score(0.30, 0.72, self.zone), 0.70)

    def test_fora_da_zona_decai_ate_a_tolerancia(self):
        meia = zone_score(0.50, 0.72 - 0.09, self.zone)
        limite = zone_score(0.50, 0.72 - 0.18, self.zone)
        self.assertAlmostEqual(meia, 0.35)
        self.assertAlmostEqual(limite, 0.0)
        self.assertEqual(zone_score(0.50, 0.72 - 1.0, self.zone), 0.0)

    def test_decaimento_isotropico_nas_tolerancias(self):
        # 0.09 equivale a meia tolerância em u e em v -> mesma pontuação
        self.assertAlmostEqual(
            zone_score(0.30 - 0.09, 0.91, self.zone),
            zone_score(0.50, 0.72 - 0.09, self.zone),
        )

    def test_centro_de_cada_zona_do_corpo_valida(self):
        for nome in ("HEAD", "TORSO", "HANDS"):
            geometria = get_zone(nome)
            u, v = geometria.center
            self.assertAlmostEqual(zone_score(u, v, geometria), 1.0, msg=nome)


class ProximityTest(unittest.TestCase):
    def test_gaussiana(self):
        self.assertAlmostEqual(gaussian_proximity(0.0, 0.5), 1.0)
        self.assertLess(gaussian_proximity(1.0, 0.5), 0.2)
        self.assertAlmostEqual(gaussian_proximity(0.5, 0.0), 0.0)

    def test_epi_no_alto_nao_e_punido(self):
        self.assertAlmostEqual(person_relative_proximity(0.5, 0.95, 0.5, 0.25), 1.0)

    def test_distancia_horizontal_reduz_proximidade(self):
        self.assertLess(person_relative_proximity(1.5, 0.95, 0.5, 0.25), 0.2)

    def test_fora_da_faixa_vertical(self):
        self.assertEqual(person_relative_proximity(0.5, -0.5, 0.5, 0.25), 0.0)
        self.assertEqual(person_relative_proximity(0.5, 2.0, 0.5, 0.25), 0.0)


class OverlapTest(unittest.TestCase):
    def test_epi_dentro_da_pessoa(self):
        interno = make_bbox(500, 700, 40, 40)
        self.assertGreater(overlap_score(interno, PERSON_BOX, 0.2, 0.1), 0.9)

    def test_epi_longe_da_pessoa(self):
        longe = make_bbox(1600, 200, 40, 40)
        self.assertEqual(overlap_score(longe, PERSON_BOX, 0.2, 0.1), 0.0)


class HomographyTest(unittest.TestCase):
    MATRIX = (
        (0.0040, -0.0002, 0.85),
        (0.0001, -0.0042, 1.15),
        (-0.0000009, 0.0000021, 1.0),
    )

    def test_protecao_de_ponto(self):
        x, y = apply_homography(self.MATRIX, (1000, 500))
        self.assertAlmostEqual(x, 4.75, places=2)
        self.assertAlmostEqual(y, -0.85, places=2)

    def test_distancia_no_plano_do_ambiente(self):
        distancia = ground_distance_m(self.MATRIX, (1000, 500), (1250, 500), 1.0)
        self.assertAlmostEqual(distancia, 1.0, places=2)

    def test_sem_calibracao_nao_ha_distancia(self):
        self.assertIsNone(ground_distance_m(None, (0, 0), (1, 1), 1.0))

    def test_conversao_de_unidade_do_referencial(self):
        distancia = ground_distance_m(self.MATRIX, (0, 0), (250, 0), 0.01)
        self.assertAlmostEqual(distancia, 0.01, places=3)


if __name__ == "__main__":
    unittest.main()
