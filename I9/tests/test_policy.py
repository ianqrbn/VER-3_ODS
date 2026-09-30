"""Testes da política de EPI (carregamento, aliases e validações)."""

from __future__ import annotations

import unittest

from tests.helpers import default_policy
from src.domain.policy import EquipmentPolicy


def minimal(**overrides):
    data = {
        "policy_id": "teste",
        "version": "1.0",
        "equipment": [
            {
                "class": "CAPACETES",
                "aliases": ["capacete"],
                "required": True,
                "u_range": [0.3, 0.7],
                "v_range": [0.7, 1.1],
            }
        ],
    }
    data.update(overrides)
    return data


class PolicyLoadingTest(unittest.TestCase):
    def test_politica_padrao_do_projeto(self):
        policy = default_policy()
        self.assertEqual(policy.policy_id, "default")
        self.assertEqual(
            policy.class_order, ("CAPACETES", "COLETES", "LUVAS")
        )
        self.assertEqual(policy.required_classes(), ("CAPACETES", "COLETES", "LUVAS"))

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

    def test_regra_com_zonas_e_tolerancias(self):
        policy = default_policy()
        capacete = policy.rules["CAPACETES"]
        self.assertEqual(capacete.zone, "HEAD")
        self.assertAlmostEqual(capacete.v_min, 0.72)
        self.assertAlmostEqual(capacete.v_max, 1.10)
        self.assertAlmostEqual(capacete.center[0], 0.5)


class PolicyValidationTest(unittest.TestCase):
    def test_classe_duplicada(self):
        data = minimal()
        data["equipment"].append(dict(data["equipment"][0]))
        with self.assertRaisesRegex(ValueError, "duplicada"):
            EquipmentPolicy.from_dict(data)

    def test_alias_ambiguo(self):
        data = minimal()
        data["equipment"].append(
            {
                "class": "COLETES",
                "aliases": ["capacete"],
                "u_range": [0.2, 0.8],
                "v_range": [0.4, 0.7],
            }
        )
        with self.assertRaisesRegex(ValueError, "ambíguo"):
            EquipmentPolicy.from_dict(data)

    def test_intervalo_invertido(self):
        data = minimal()
        data["equipment"][0]["u_range"] = [0.9, 0.2]
        with self.assertRaisesRegex(ValueError, "max > min"):
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


if __name__ == "__main__":
    unittest.main()
