"""Testes do registro de zonas do corpo (conhecimento de domínio do verificador)."""

from __future__ import annotations

import unittest

from src.domain.body_zones import (
    ZONAS,
    BodyZone,
    ZoneGeometry,
    get_zone,
    resolve_zone,
)


class ZoneGeometryTest(unittest.TestCase):
    def test_geometria_invertida_e_rejeitada(self):
        with self.assertRaises(ValueError):
            ZoneGeometry(u_min=0.8, u_max=0.2, v_min=0.0, v_max=1.0)
        with self.assertRaises(ValueError):
            ZoneGeometry(u_min=0.0, u_max=1.0, v_min=0.9, v_max=0.1)

    def test_tolerancia_nao_positiva_e_rejeitada(self):
        with self.assertRaises(ValueError):
            ZoneGeometry(u_min=0.0, u_max=1.0, v_min=0.0, v_max=1.0, tolerance_u=0.0)

    def test_centro_da_zona(self):
        zona = ZoneGeometry(u_min=0.2, u_max=0.8, v_min=0.4, v_max=0.6)
        self.assertEqual(zona.center, (0.5, 0.5))


class ZoneRegistryTest(unittest.TestCase):
    def test_toda_zona_tem_geometria(self):
        for zone in BodyZone:
            self.assertIn(zone, ZONAS)

    def test_lookup_case_insensitive(self):
        for nome in ("HEAD", "head", " Head "):
            self.assertIs(get_zone(nome), ZONAS[BodyZone.HEAD])

    def test_resolve_devolve_o_enum_canonico(self):
        self.assertIs(resolve_zone("torso"), BodyZone.TORSO)
        self.assertEqual(resolve_zone("hands").value, "HANDS")

    def test_zona_desconhecida_e_rejeitada(self):
        with self.assertRaisesRegex(ValueError, "zona desconhecida"):
            get_zone("EARS")
        # a mensagem lista as zonas disponíveis para orientar a configuração
        with self.assertRaisesRegex(ValueError, "HEAD"):
            get_zone("EARS")

    def test_geometria_das_zonas_padrao(self):
        cabeca = get_zone("HEAD")
        tronco = get_zone("TORSO")
        maos = get_zone("HANDS")

        # a cabeça fica no topo (v alto) e as mãos na parte baixa
        self.assertGreater(cabeca.v_min, tronco.v_min)
        self.assertGreater(tronco.v_min, maos.v_min)
        # todas centradas horizontalmente
        for zona in (cabeca, tronco, maos):
            self.assertAlmostEqual(zona.center[0], 0.5, places=2)
        # capacete pode ultrapassar o topo da bounding box da pessoa
        self.assertGreater(cabeca.v_max, 1.0)


if __name__ == "__main__":
    unittest.main()
