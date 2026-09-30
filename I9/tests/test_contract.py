"""Testes de contrato: evento do I2 (com calibração do I3) -> evento do I9."""

from __future__ import annotations

import json
import unittest

from tests.helpers import default_policy, make_calibration, quiet
import main as app
from src.adapters.mock_adapters import (
    MockCalibrationAdapter,
    MockConsoleOutputAdapter,
    MockIngestionAdapter,
)
from src.core.calibration import CalibrationStore
from src.core.inference import RelationInferenceModule
from src.core.pairing import PairingModule
from src.core.pipeline import I9Pipeline
from src.domain.models import RELATIONAL_SCHEMA, SCHEMA_VERSION

CAMPOS_PAYLOAD = (
    "camera_id",
    "session_id",
    "frame",
    "captured_at",
    "frame_width",
    "frame_height",
    "calibration_version",
    "calibration_status",
    "policy_id",
    "policy_version",
    "relations",
    "unassociated_equipment",
    "ignored_tracks",
)


def run_pipeline(max_frames: int = 3, as_json: bool = False):
    pipeline = app.build_pipeline(max_frames=max_frames, as_json=as_json)
    events = []
    with quiet():
        while True:
            event = pipeline.run_once()
            if event is None:
                break
            events.append(event)
    return pipeline, events


class EventEnvelopeTest(unittest.TestCase):
    def test_envelope_de_saida(self):
        _, events = run_pipeline()
        self.assertEqual(len(events), 3)
        for event in events:
            body = event.as_dict()
            self.assertEqual(body["message_type"], "event")
            self.assertEqual(body["schema"], RELATIONAL_SCHEMA)
            self.assertEqual(body["schema_version"], SCHEMA_VERSION)
            self.assertEqual(body["producer"], "I9")
            self.assertIn("published_at", body)
            for campo in CAMPOS_PAYLOAD:
                self.assertIn(campo, body["payload"])

    def test_evento_e_serializavel_em_json(self):
        _, events = run_pipeline(max_frames=1)
        json.dumps(events[0].as_dict(), ensure_ascii=False)

    def test_momentos_do_quadro_sao_repassados(self):
        _, events = run_pipeline(max_frames=1)
        payload = events[0].as_dict()["payload"]
        self.assertEqual(payload["camera_id"], "CAM-01")
        self.assertEqual(payload["frame"], 1001)
        self.assertEqual(payload["frame_width"], 1920)
        self.assertEqual(payload["frame_height"], 1080)
        self.assertTrue(payload["captured_at"].endswith("Z"))

    def test_calibracao_aparece_no_evento(self):
        _, events = run_pipeline(max_frames=1)
        payload = events[0].as_dict()["payload"]
        self.assertEqual(payload["calibration_status"], "valid")
        self.assertEqual(payload["calibration_version"], "cam-01-v3")


class TrackPassthroughTest(unittest.TestCase):
    def test_tracks_sao_repassados_sem_alteracao(self):
        pipeline, events = run_pipeline(max_frames=1)
        originais = {t.track_id: t.as_dict() for t in pipeline.ingestion_port.frames[0].tracks}
        payload = events[0].as_dict()["payload"]

        for relation in payload["relations"]:
            self.assertEqual(relation["person"], originais[relation["person"]["track_id"]])
            for item in relation["equipment"]:
                if item["detection"]:
                    self.assertEqual(item["detection"], originais[item["detection"]["track_id"]])

    def test_todo_track_aparece_exatamente_uma_vez(self):
        pipeline, events = run_pipeline()
        for indice, event in enumerate(events):
            entrada = {t.track_id for t in pipeline.ingestion_port.frames[indice].tracks}
            self.assertEqual(event.track_ids_covered(), entrada)


class EventContentTest(unittest.TestCase):
    def test_os_tres_estados_no_mesmo_quadro(self):
        _, events = run_pipeline(max_frames=1)
        estados = {
            item["relational_state"]
            for relation in events[0].as_dict()["payload"]["relations"]
            for item in relation["equipment"]
        }
        self.assertEqual(estados, {"CORRETO", "INCORRETO", "AUSENTE"})

    def test_epi_descartado_vai_para_ignored_tracks(self):
        _, events = run_pipeline()
        ignorados = events[-1].as_dict()["payload"]["ignored_tracks"]
        self.assertEqual(len(ignorados), 1)
        self.assertEqual(ignorados[0]["reason"], "track_state_lost")
        self.assertEqual(ignorados[0]["track"]["class"], "colete")

    def test_epi_sem_dono_vai_para_unassociated(self):
        _, events = run_pipeline(max_frames=1)
        nao_relacionados = events[0].as_dict()["payload"]["unassociated_equipment"]
        self.assertEqual(len(nao_relacionados), 1)
        self.assertEqual(nao_relacionados[0]["reason"], "below_association_threshold")

    def test_ausencia_tem_deteccao_nula(self):
        _, events = run_pipeline(max_frames=1)
        ausentes = [
            item
            for relation in events[0].as_dict()["payload"]["relations"]
            for item in relation["equipment"]
            if item["relational_state"] == "AUSENTE"
        ]
        self.assertTrue(ausentes)
        for item in ausentes:
            self.assertIsNone(item["detection"])
            self.assertLessEqual(item["confidence_pct"], 70.0)

    def test_quadro_sem_pessoas_publica_evento_vazio(self):
        pipeline = app.build_pipeline(max_frames=0)
        self.assertIsNone(pipeline.run_once())

    def test_saida_no_console_em_json(self):
        _, events = run_pipeline(max_frames=1, as_json=True)
        self.assertEqual(len(events), 1)


class CalibrationBehaviourTest(unittest.TestCase):
    def test_calibracao_valida_e_armazenada(self):
        store = CalibrationStore(default_policy().calibration)
        self.assertTrue(store.upsert(make_calibration()))
        self.assertEqual(store.status("CAM-01").version, "cam-01-v3")
        self.assertEqual(store.status("CAM-01").status, "valid")

    def test_calibracao_com_rms_alto_e_rejeitada(self):
        store = CalibrationStore(default_policy().calibration)
        self.assertFalse(store.upsert(make_calibration(reprojection_rms_cm=25.0)))
        self.assertIsNone(store.get("CAM-01"))
        status = store.status("CAM-01")
        self.assertEqual(status.status, "rejected")
        self.assertIn("reprojection_rms_cm", status.reason)

    def test_calibracao_com_poucos_holdout_e_rejeitada(self):
        store = CalibrationStore(default_policy().calibration)
        self.assertFalse(store.upsert(make_calibration(holdout_points=1)))
        self.assertEqual(store.status("CAM-01").status, "rejected")

    def test_camera_sem_calibracao_publica_missing(self):
        class SemCalibracao:
            def get_calibration(self, camera_id):
                return None

        policy = default_policy()
        pipeline = I9Pipeline(
            ingestion_port=MockIngestionAdapter(max_frames=1),
            output_port=MockConsoleOutputAdapter(),
            calibration_port=SemCalibracao(),
            pairing_module=PairingModule(policy, CalibrationStore(policy.calibration)),
            inference_module=RelationInferenceModule(policy),
            policy=policy,
        )
        with quiet():
            payload = pipeline.run_once().as_dict()["payload"]
        self.assertEqual(payload["calibration_status"], "missing")
        self.assertIsNone(payload["calibration_version"])
        # a verificação geométrica continua válida sem homografia
        estados = [item["relational_state"] for item in payload["relations"][0]["equipment"]]
        self.assertIn("CORRETO", estados)

    def test_adapter_devolve_apenas_a_sua_camera(self):
        adapter = MockCalibrationAdapter()
        self.assertIsNone(adapter.get_calibration("CAM-99"))


if __name__ == "__main__":
    unittest.main()
