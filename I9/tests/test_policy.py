"""Testes da política de EPI (carregamento, aliases, zonas e validações)."""

from __future__ import annotations

import unittest

from tests.helpers import default_policy
from src.domain.body_zones import BodyZone
from src.domain.policy import EquipmentPolicy, ZoneRule


def regra_center(regra: ZoneRule):
    centro = regra.geometry.center
    return (round(centro[0], 2), round(centro[1], 2))


def regra_tolerance(regra: ZoneRule):
    return (regra.geometry.tolerance_u, regra.geometry.tolerance_v)


def minimal(**overrides):
    data = {
        "policy_id": "teste",
        "version": "1.0",
        "equipment": [
            {
                "class": "CAPACETES",
                "aliases": ["capacete"],
                "required": True,
                "zone": "HEAD",
            }
        ],
    }
    data.update(overrides)
    return data


class PolicyLoadingTest(unittest.TestCase):
    def test_politica_padrao_do_projeto(self):
        policy = default_policy()
        self.assertEqual(policy.policy_id, "default")
        self.assertEqual(policy.class_order, ("CAPACETES", "COLETES"))
        self.assertEqual(policy.required_classes(), ("CAPACETES", "COLETES"))

    def test_zonas_associadas_as_classes(self):
        policy = default_policy()
        self.assertIs(policy.zone_for("capacete"), BodyZone.HEAD)
        self.assertIs(policy.zone_for("colete"), BodyZone.TORSO)
        self.assertIsNone(policy.zone_for("protetor_auricular"))

    def test_geometria_vem_do_motor(self):
        policy = default_policy()
        regra = policy.rules["CAPACETES"]
        self.assertEqual(regra_center(regra), (0.5, 0.91))
        self.assertEqual(regra_tolerance(regra), (0.18, 0.18))

    def test_alias_case_insensitive(self):
        policy = default_policy()
        for bruto in ("capacete", "CAPACETE", "Capacete", "capacetes", "helmet"):
            self.assertEqual(policy.canonical_for(bruto), "CAPACETES")
        self.assertIsNone(policy.canonical_for("protetor_auricular"))

    def test_deteccao_de_pessoa_e_classe_desconhecida(self):
        policy = default_policy()
        self.assertTrue(policy.is_person("pessoa"))
        self.assertTrue(policy.is_person("Person"))
        self.assertFalse(policy.canonical_for("pessoa"))
        self.assertTrue(policy.detect_unknown_class("protetor_auricular"))
        self.assertFalse(policy.detect_unknown_class("capacete"))
        self.assertFalse(policy.detect_unknown_class("pessoa"))

    def test_min_association_tem_default_do_motor(self):
        policy = default_policy()
        self.assertEqual(policy.rules["CAPACETES"].min_association, 0.45)

    def test_classe_opcional(self):
        data = minimal()
        data["equipment"][0]["required"] = False
        policy = EquipmentPolicy.from_dict(data)
        self.assertFalse(policy.rules["CAPACETES"].required)
        self.assertEqual(policy.required_classes(), ())


class PolicyValidationTest(unittest.TestCase):
    def test_classe_duplicada(self):
        data = minimal()
        data["equipment"].append(dict(data["equipment"][0]))
        with self.assertRaisesRegex(ValueError, "duplicada"):
            EquipmentPolicy.from_dict(data)

    def test_alias_ambiguo(self):
        data = minimal()
        data["equipment"].append(
            {"class": "COLETES", "aliases": ["capacete"], "zone": "TORSO"}
        )
        with self.assertRaisesRegex(ValueError, "ambíguo"):
            EquipmentPolicy.from_dict(data)

    def test_zona_desconhecida(self):
        data = minimal()
        data["equipment"][0]["zone"] = "EARS"
        with self.assertRaisesRegex(ValueError, "zona desconhecida"):
            EquipmentPolicy.from_dict(data)

    def test_zona_ausente(self):
        data = minimal()
        del data["equipment"][0]["zone"]
        with self.assertRaisesRegex(ValueError, "zone"):
            EquipmentPolicy.from_dict(data)

    def test_pessoa_nao_pode_ser_classe_de_epi(self):
        data = minimal()
        data["equipment"][0]["aliases"] = ["pessoa"]
        with self.assertRaisesRegex(ValueError, "pessoa"):
            EquipmentPolicy.from_dict(data)

    def test_ausencia_acima_do_teto(self):
        data = minimal()
        data["confidence"] = {"absence_base": 0.9, "absence_max": 0.5}
        with self.assertRaisesRegex(ValueError, "absence_base"):
            EquipmentPolicy.from_dict(data)

    def test_lista_de_equipamentos_vazia(self):
        with self.assertRaisesRegex(ValueError, "equipment"):
            EquipmentPolicy.from_dict(minimal(equipment=[]))

    def test_pesos_de_associacao_invalidos(self):
        data = minimal()
        data["association"] = {"weight_overlap": 0.0, "weight_proximity": 0.0}
        with self.assertRaisesRegex(ValueError, "pesos"):
            EquipmentPolicy.from_dict(data)


def regra_center(regra):
    centro = regra.geometry.center
    return (round(centro[0], 2), round(centro[1], 2))


def regra_tolerance(regra):
    return (regra.geometry.tolerance_u, regra.geometry.tolerance_v)


if __name__ == "__main__":
    unittest.main()
