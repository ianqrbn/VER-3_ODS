"""Testes da inferência de estado relacional e da pontuação de confiança."""

from __future__ import annotations

import unittest

from tests.helpers import (
    PERSON_BOX,
    default_policy,
    make_bbox,
    make_calibration,
    make_frame,
    make_track,
    uncapped_policy,
)
from src.core.calibration import CalibrationStore
from src.core.inference import RelationInferenceModule
from src.core.pairing import PairingModule
from src.domain.models import RelationalState

PESSOA = make_track(1, "pessoa", PERSON_BOX)
CAPACETE_OK = make_track(10, "capacete", make_bbox(468, 884, 144, 150))       # cabeça
COLETE_OK = make_track(11, "colete", make_bbox(432, 580, 200, 200))            # tronco
COLETE_NA_CINTURA = make_track(12, "colete", make_bbox(430, 346, 220, 200))    # quadril
LUVAS_OK = make_track(13, "luvas", make_bbox(415, 545, 50, 70))
EPI_LONGE = make_bbox(1600, 200, 100, 120)


def evaluate(tracks, policy=None):
    policy = policy or default_policy()
    store = CalibrationStore(policy.calibration)
    store.upsert(make_calibration())
    pairing = PairingModule(policy=policy, calibration_store=store).pair(make_frame(tracks))
    return RelationInferenceModule(policy=policy).infer(pairing)


def item_for(evaluations, index: int, canonical: str):
    return {e.canonical_class: e for e in evaluations[index].equipment}[canonical]


class RelationalStateTest(unittest.TestCase):
    def test_epi_no_lugar_certo(self):
        avaliacoes = evaluate([PESSOA, CAPACETE_OK, COLETE_OK, LUVAS_OK])
        for canonical in ("CAPACETES", "COLETES", "LUVAS"):
            item = item_for(avaliacoes, 0, canonical)
            self.assertIs(item.state, RelationalState.CORRETO, canonical)
            self.assertGreater(item.confidence_pct, 0.0)
            self.assertLessEqual(item.confidence_pct, 95.0)
            self.assertIsNotNone(item.track)

    def test_epi_no_lugar_errado(self):
        avaliacoes = evaluate([PESSOA, CAPACETE_OK, COLETE_NA_CINTURA, LUVAS_OK])
        item = item_for(avaliacoes, 0, "COLETES")
        self.assertIs(item.state, RelationalState.INCORRETO)
        self.assertIsNotNone(item.track)
        self.assertLess(item.evidence["placement_score_pct"], 75.0)
        self.assertGreaterEqual(item.evidence["association_score_pct"], 45.0)

    def test_epi_ausente_gera_registro_sintetico(self):
        avaliacoes = evaluate([PESSOA, CAPACETE_OK, COLETE_OK])
        item = item_for(avaliacoes, 0, "LUVAS")
        self.assertIs(item.state, RelationalState.AUSENTE)
        self.assertIsNone(item.track)
        self.assertTrue(item.required)
        self.assertLessEqual(item.confidence_pct, 70.0)
        self.assertEqual(item.evidence["reason"], "no_candidate_in_person_region")

    def test_pessoa_sem_nenhum_epi(self):
        avaliacoes = evaluate([PESSOA])
        estados = {e.canonical_class: e.state for e in avaliacoes[0].equipment}
        self.assertEqual(
            estados,
            {
                "CAPACETES": RelationalState.AUSENTE,
                "COLETES": RelationalState.AUSENTE,
                "LUVAS": RelationalState.AUSENTE,
            },
        )

    def test_apenas_tres_estados_no_contrato(self):
        avaliacoes = evaluate([PESSOA, CAPACETE_OK, COLETE_NA_CINTURA])
        for item in avaliacoes[0].equipment:
            self.assertIn(
                item.state,
                (RelationalState.CORRETO, RelationalState.INCORRETO, RelationalState.AUSENTE),
            )


class ConfidenceTest(unittest.TestCase):
    def test_track_previsto_reduz_confianca(self):
        # política sem teto de confiança para que a razão seja exatamente 0.70
        previsto_track = make_track(
            10, "capacete", make_bbox(468, 884, 144, 150), state="predicted"
        )
        confirmado = item_for(
            evaluate([PESSOA, CAPACETE_OK, COLETE_OK, LUVAS_OK], uncapped_policy()),
            0,
            "CAPACETES",
        )
        previsto = item_for(
            evaluate([PESSOA, previsto_track, COLETE_OK, LUVAS_OK], uncapped_policy()),
            0,
            "CAPACETES",
        )
        self.assertEqual(previsto.evidence["penalty"], "predicted_track")
        self.assertAlmostEqual(
            previsto.confidence_pct,
            round(confirmado.confidence_pct * 0.70, 2),
            places=2,
        )
        # com o teto padrão, a confiança continua bem menor que a do confirmado
        self.assertLess(previsto.confidence_pct, confirmado.confidence_pct)

    def test_candidato_sem_dono_reduz_confianca_da_ausencia(self):
        sem_candidato = item_for(evaluate([PESSOA, CAPACETE_OK, COLETE_OK]), 0, "LUVAS")
        com_candidato = item_for(
            evaluate(
                [
                    PESSOA,
                    CAPACETE_OK,
                    COLETE_OK,
                    make_track(14, "luvas", EPI_LONGE),
                ]
            ),
            0,
            "LUVAS",
        )
        self.assertLess(com_candidato.confidence_pct, sem_candidato.confidence_pct)
        self.assertLessEqual(com_candidato.confidence_pct, 70.0 * 0.85)

    def test_teto_de_confianca(self):
        item = item_for(evaluate([PESSOA, CAPACETE_OK, COLETE_OK, LUVAS_OK]), 0, "COLETES")
        self.assertLessEqual(item.confidence_pct, 95.0)

    def test_evidencia_contem_posicao_normalizada(self):
        item = item_for(evaluate([PESSOA, CAPACETE_OK, COLETE_OK, LUVAS_OK]), 0, "CAPACETES")
        centro = item.evidence["person_normalized_center"]
        self.assertAlmostEqual(centro["u"], 0.5, places=2)
        self.assertGreater(centro["v"], 0.8)  # cabeça fica no topo (origem inferior)
        self.assertIn("ground_distance_m", item.evidence)
        self.assertEqual(item.evidence["expected_zone"], "HEAD")


if __name__ == "__main__":
    unittest.main()
