"""Testes da associação geométrica pessoa <-> EPI."""

from __future__ import annotations

import unittest

from tests.helpers import (
    PERSON_BOX,
    SECOND_PERSON_BOX,
    default_policy,
    make_bbox,
    make_calibration,
    make_frame,
    make_track,
)
from src.core.calibration import CalibrationStore
from src.core.pairing import PairingModule


def build_module(with_calibration: bool = True) -> PairingModule:
    policy = default_policy()
    store = CalibrationStore(policy.calibration)
    if with_calibration:
        store.upsert(make_calibration())
    return PairingModule(policy=policy, calibration_store=store)


def relation_for(result, track_id: int):
    for relation in result.relations:
        if relation.person.track_id == track_id:
            return relation
    raise AssertionError(f"pessoa {track_id} ausente no resultado")


def match_for(relation, canonical: str):
    for match in relation.equipment:
        if match.canonical_class == canonical:
            return match
    return None


class PairingTest(unittest.TestCase):
    def setUp(self):
        self.pessoa = make_track(1, "pessoa", PERSON_BOX)
        # capacete bem posicionado (topo da pessoa) e colete deslocado para o quadril
        self.capacete = make_track(10, "capacete", make_bbox(468, 884, 144, 150))
        self.colete = make_track(11, "colete", make_bbox(430, 346, 220, 200))
        self.pessoa_2 = make_track(2, "pessoa", SECOND_PERSON_BOX)
        self.capacete_2 = make_track(20, "capacete", make_bbox(1147, 864, 134, 150))

    def test_associa_epi_a_unica_pessoa(self):
        frame = make_frame([self.pessoa, self.capacete, self.colete, self.pessoa_2, self.capacete_2])
        result = build_module().pair(frame)

        self.assertEqual([r.person.track_id for r in result.relations], [1, 2])
        primeira = relation_for(result, 1)
        segunda = relation_for(result, 2)

        self.assertEqual(match_for(primeira, "CAPACETES").track.track_id, 10)
        self.assertEqual(match_for(primeira, "COLETES").track.track_id, 11)
        self.assertEqual(match_for(segunda, "CAPACETES").track.track_id, 20)
        self.assertIsNone(match_for(segunda, "COLETES"))
        self.assertEqual(result.unassociated_equipment, [])

    def test_epi_longe_vai_para_nao_relacionados(self):
        perdido = make_track(30, "capacete", make_bbox(1600, 200, 100, 120))
        frame = make_frame([self.pessoa, self.capacete, perdido])
        result = build_module().pair(frame)

        self.assertEqual(len(result.unassociated_equipment), 1)
        item = result.unassociated_equipment[0]
        self.assertEqual(item.track.track_id, 30)
        self.assertEqual(item.canonical_class, "CAPACETES")
        self.assertLess(item.best_association_score_pct, 45.0)

    def test_epi_perdido_e_classe_desconhecida_sao_descartados(self):
        perdido = make_track(11, "colete", make_bbox(430, 346, 220, 200), state="lost")
        desconhecido = make_track(31, "protetor_auricular", make_bbox(500, 600, 40, 40))
        frame = make_frame([self.pessoa, self.capacete, perdido, desconhecido])
        result = build_module().pair(frame)

        reasons = {item.track.track_id: item.reason for item in result.ignored_tracks}
        self.assertEqual(reasons[11], "track_state_lost")
        self.assertEqual(reasons[31], "class_not_in_policy")
        self.assertEqual(result.unassociated_equipment, [])

    def test_pessoa_perdida_nao_gera_relacao(self):
        perdida = make_track(1, "pessoa", PERSON_BOX, state="lost")
        result = build_module().pair(make_frame([perdida, self.capacete]))
        self.assertEqual(result.relations, [])
        self.assertEqual(len(result.unassociated_equipment), 1)

    def test_associacao_e_um_para_um(self):
        # um único capacete entre duas pessoas deve ficar com apenas uma delas
        quadro_1 = make_frame([self.pessoa, self.pessoa_2, self.capacete_2])
        quadro_2 = make_frame([self.pessoa, self.pessoa_2, self.capacete])
        module = build_module()

        resultado_1 = module.pair(quadro_1)
        resultado_2 = module.pair(quadro_2)

        for resultado in (resultado_1, resultado_2):
            donos = [
                relation.person.track_id
                for relation in resultado.relations
                if match_for(relation, "CAPACETES") is not None
            ]
            self.assertEqual(len(donos), 1)

    def test_corte_metrico_rejeita_epi_no_outro_extremo_da_area(self):
        # pessoa isolada em x=0 e capacete em x=1800: rejeitados pelo raio em metros
        pessoa = make_track(1, "pessoa", make_bbox(0, 0, 200, 700))
        capacete = make_track(10, "capacete", make_bbox(1500, 600, 100, 100))
        result = build_module().pair(make_frame([pessoa, capacete]))

        self.assertEqual(result.relations[0].equipment, ())
        self.assertEqual(len(result.unassociated_equipment), 1)

    def test_sem_calibracao_a_associacao_continua_funcionando(self):
        result = build_module(with_calibration=False).pair(
            make_frame([self.pessoa, self.capacete])
        )
        match = match_for(result.relations[0], "CAPACETES")
        self.assertIsNotNone(match)
        self.assertIsNone(match.ground_distance_m)

    def test_ordem_determinista(self):
        module = build_module()
        frame = make_frame([self.pessoa_2, self.pessoa, self.colete, self.capacete])
        primeiro = module.pair(frame)
        segundo = module.pair(frame)
        self.assertEqual(
            [(r.person.track_id, [m.track.track_id for m in r.equipment]) for r in primeiro.relations],
            [(r.person.track_id, [m.track.track_id for m in r.equipment]) for r in segundo.relations],
        )


if __name__ == "__main__":
    unittest.main()
