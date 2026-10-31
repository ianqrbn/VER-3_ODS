"""Testes da inferência de estado relacional e da pontuação de confiança."""

from __future__ import annotations

import unittest

from tests.helpers import (
    PERSON_BOX,
    default_policy,
    make_bbox,
    make_calibration,
    make_frame,
    make_detection,
    policy_from,
    uncapped_policy,
)
from src.core.calibration import CalibrationStore
from src.core.inference import RelationInferenceModule
from src.core.pairing import PairingModule
from src.domain.models import RelationalState

PESSOA = make_detection(1, "pessoa", PERSON_BOX)
CAPACETE_OK = make_detection(10, "capacete", make_bbox(468, 884, 144, 150))       # cabeça
COLETE_OK = make_detection(11, "colete", make_bbox(432, 580, 200, 200))            # tronco
COLETE_NA_CINTURA = make_detection(12, "colete", make_bbox(430, 346, 220, 200))    # quadril
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
        avaliacoes = evaluate([PESSOA, CAPACETE_OK, COLETE_OK])
        for canonical in ("capacete", "colete"):
            item = item_for(avaliacoes, 0, canonical)
            self.assertIs(item.state, RelationalState.CORRETO, canonical)
            self.assertGreater(item.confidence, 0.0)
            self.assertLessEqual(item.confidence, 0.95)
            self.assertIsNotNone(item.detection)
            self.assertFalse(item.uncertain)

    def test_epi_no_lugar_errado(self):
        avaliacoes = evaluate([PESSOA, CAPACETE_OK, COLETE_NA_CINTURA])
        item = item_for(avaliacoes, 0, "colete")
        self.assertIs(item.state, RelationalState.INCORRETO)
        self.assertIsNotNone(item.detection)
        self.assertLess(item.evidence["placement_score"], 0.75)
        self.assertGreaterEqual(item.evidence["association_score"], 0.45)

    def test_pessoa_sem_nenhum_epi(self):
        avaliacoes = evaluate([PESSOA])
        estados = {e.canonical_class: e.state for e in avaliacoes[0].equipment}
        self.assertEqual(
            estados,
            {
                "capacete": RelationalState.AUSENTE,
                "colete": RelationalState.AUSENTE,
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
    def test_confianca_da_deteccao_do_i1_escala_a_confianca(self):
        # política sem teto de confiança para que a razão seja exatamente 0.70
        fraco = make_detection(10, "capacete", make_bbox(468, 884, 144, 150), confidence=0.70)
        firme = item_for(
            evaluate([PESSOA, CAPACETE_OK, COLETE_OK], uncapped_policy()),
            0,
            "capacete",
        )
        reduzido = item_for(
            evaluate([PESSOA, fraco, COLETE_OK], uncapped_policy()),
            0,
            "capacete",
        )
        self.assertEqual(reduzido.evidence["detection_confidence"], 0.70)
        self.assertAlmostEqual(reduzido.confidence, firme.confidence * 0.70, places=6)

    def test_ausencia_escala_com_a_confianca_da_pessoa(self):
        pessoa = make_detection(1, "pessoa", PERSON_BOX, confidence=0.5)
        item = item_for(evaluate([pessoa]), 0, "capacete")
        self.assertAlmostEqual(item.confidence, 0.62 * 0.5, places=6)

    def test_teto_de_confianca(self):
        item = item_for(evaluate([PESSOA, CAPACETE_OK, COLETE_OK]), 0, "colete")
        self.assertLessEqual(item.confidence, 0.95)


class UncertainTest(unittest.TestCase):
    def test_baixa_confianca_marca_uncertain(self):
        fraco = make_detection(10, "capacete", make_bbox(468, 884, 144, 150), confidence=0.40)
        avaliacoes = evaluate([PESSOA, fraco, COLETE_OK])
        self.assertTrue(item_for(avaliacoes, 0, "capacete").uncertain)
        self.assertFalse(item_for(avaliacoes, 0, "colete").uncertain)
        self.assertTrue(avaliacoes[0].uncertain)
        self.assertEqual(avaliacoes[0].uncertain_reasons, ())

    def test_oclusao_severa_marca_todos_os_itens(self):
        # segunda pessoa quase sobreposta à primeira
        ocluida = make_detection(2, "pessoa", make_bbox(440, 300, 240, 700))
        avaliacoes = evaluate([PESSOA, ocluida, CAPACETE_OK, COLETE_OK])
        for avaliacao in avaliacoes:
            self.assertEqual(avaliacao.uncertain_reasons, ("severe_occlusion",))
            self.assertTrue(all(e.uncertain for e in avaliacao.equipment))

    def test_pessoas_separadas_nao_sao_ocluidas(self):
        outra = make_detection(2, "pessoa", make_bbox(1100, 300, 220, 680))
        avaliacoes = evaluate([PESSOA, outra, CAPACETE_OK, COLETE_OK])
        self.assertEqual(avaliacoes[0].uncertain_reasons, ())

    def test_evidencia_contem_posicao_normalizada(self):
        item = item_for(evaluate([PESSOA, CAPACETE_OK, COLETE_OK]), 0, "capacete")
        centro = item.evidence["person_normalized_center"]
        self.assertAlmostEqual(centro["u"], 0.5, places=2)
        self.assertGreater(centro["v"], 0.8)  # cabeça fica no topo (origem inferior)
        self.assertIn("ground_distance_m", item.evidence)
        self.assertEqual(item.evidence["expected_zone"], "HEAD")


if __name__ == "__main__":
    unittest.main()


class PolicyDrivenClassTest(unittest.TestCase):
    """A Opção A mantém a configuração no nível de 'qual EPI em qual zona'."""

    def test_classe_opcional_nao_gera_ausente(self):
        def mutation(data):
            data["equipment"][1]["required"] = False  # colete deixa de ser obrigatória

        # colete está presente, então deve ser retornado (como CORRETO)
        avaliacoes = evaluate([PESSOA, CAPACETE_OK, COLETE_OK], policy_from(mutation))
        classes = {e.canonical_class for e in avaliacoes[0].equipment}
        self.assertEqual(classes, {"capacete", "colete"})

        # colete ausente e opcional -> não deve gerar AUSENTE
        avaliacoes = evaluate([PESSOA, CAPACETE_OK], policy_from(mutation))
        classes = {e.canonical_class for e in avaliacoes[0].equipment}
        self.assertEqual(classes, {"capacete"})

    def test_classe_nova_reaproveita_zona_existente(self):
        def mutation(data):
            data["equipment"].append(
                {
                    "class": "PROTETORES_AURICULARES",
                    "aliases": ["protetor_auricular", "protetor"],
                    "required": True,
                    "zone": "HEAD",
                }
            )

        policy = policy_from(mutation)
        # nenhuma mudança de código: a regra aponta para uma zona do registro
        self.assertIs(policy.zone_for("protetor_auricular").name, "HEAD")
        avaliacoes = evaluate([PESSOA, CAPACETE_OK, COLETE_OK], policy)
        protetor = item_for(avaliacoes, 0, "PROTETORES_AURICULARES")
        self.assertIs(protetor.state, RelationalState.AUSENTE)
        self.assertEqual(protetor.evidence["zone"], "HEAD")

    def test_classe_nova_detectada_usa_a_zona_declarada(self):
        def mutation(data):
            data["equipment"].append(
                {
                    "class": "PROTETORES_AURICULARES",
                    "aliases": ["protetor_auricular"],
                    "required": True,
                    "zone": "HEAD",
                }
            )

        protetor_track = make_detection(14, "protetor_auricular", make_bbox(500, 900, 40, 40))
        avaliacoes = evaluate([PESSOA, CAPACETE_OK, COLETE_OK, protetor_track], policy_from(mutation))
        protetor = item_for(avaliacoes, 0, "PROTETORES_AURICULARES")
        self.assertIs(protetor.state, RelationalState.CORRETO)
        self.assertEqual(protetor.evidence["expected_zone"], "HEAD")
