"""Testes de contrato: `ods.i1.detections` (com `ods.i3.calibration`) -> `ods.i9.ppe_compliance`."""

from __future__ import annotations

import json
import unittest

from tests.helpers import (
    PERSON_BOX,
    ROOT,
    default_policy,
    make_bbox,
    make_calibration,
    make_detection,
    make_event,
    quiet,
)
import main as app
from src.adapters.message_adapters import (
    MessageCalibrationAdapter,
    MessageIngestionAdapter,
    MessagePublisherAdapter,
)
from src.adapters.mock_adapters import (
    MockCalibrationAdapter,
    MockConsoleOutputAdapter,
    MockIngestionAdapter,
)
from src.core.calibration import CalibrationStore
from src.core.inference import RelationInferenceModule
from src.core.pairing import PairingModule
from src.core.pipeline import I9Pipeline
from src.domain.models import COMPLIANCE_SCHEMA, SCHEMA_VERSION, DetectionFrame

EXAMPLE_I1 = ROOT / "examples" / "i1_detections.json"

CAMPOS_ENVELOPE = (
    "message_type",
    "message_id",
    "schema",
    "schema_version",
    "producer",
    "published_at",
    "captured_at",
    "source_id",
    "session_id",
    "sequence",
    "artifact_version",
    "payload",
)

CAMPOS_PAYLOAD = (
    "frame_index",
    "image_width",
    "image_height",
    "source_message_id",
    "catalog_version",
    "calibration_version",
    "calibration_status",
    "uncertain",
    "persons",
    "unassociated_equipment",
    "ignored_detections",
)

CAMPOS_ITEM = ("equipment_item", "state", "confidence", "uncertain", "detection_id", "evidence")


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


def build_message_pipeline(messages, calibrations=(), sent=None):
    policy = default_policy()
    output = (
        MessagePublisherAdapter(lambda topic, key, value: sent.append((topic, key, value)))
        if sent is not None
        else MockConsoleOutputAdapter()
    )
    return I9Pipeline(
        ingestion_port=MessageIngestionAdapter(messages),
        output_port=output,
        calibration_port=MessageCalibrationAdapter(calibrations),
        pairing_module=PairingModule(policy, CalibrationStore(policy.calibration)),
        inference_module=RelationInferenceModule(policy),
        policy=policy,
    )


class EventEnvelopeTest(unittest.TestCase):
    def test_envelope_ev_sinal(self):
        _, events = run_pipeline()
        self.assertEqual(len(events), 3)
        for event in events:
            body = event.as_dict()
            for campo in CAMPOS_ENVELOPE:
                self.assertIn(campo, body)
            self.assertEqual(body["message_type"], "event")
            self.assertEqual(body["schema"], COMPLIANCE_SCHEMA)
            self.assertEqual(body["schema"], "ods.i9.ppe_compliance")
            self.assertEqual(body["schema_version"], SCHEMA_VERSION)
            self.assertEqual(body["producer"], "I9")
            self.assertEqual(body["artifact_version"], default_policy().artifact_version)
            for campo in CAMPOS_PAYLOAD:
                self.assertIn(campo, body["payload"])
            for person in body["payload"]["persons"]:
                for item in person["equipment"]:
                    for campo in CAMPOS_ITEM:
                        self.assertIn(campo, item)

    def test_message_id_e_unico_por_evento(self):
        _, events = run_pipeline()
        self.assertEqual(len({e.message_id for e in events}), len(events))

    def test_evento_e_serializavel_em_json(self):
        _, events = run_pipeline(max_frames=1)
        json.dumps(events[0].as_dict(), ensure_ascii=False)

    def test_chave_do_quadro_e_repassada_do_i1(self):
        pipeline, events = run_pipeline(max_frames=1)
        entrada = pipeline.ingestion_port.frames[0]
        body = events[0].as_dict()
        self.assertEqual(body["source_id"], "cam0")
        self.assertEqual(body["session_id"], entrada.session_id)
        self.assertEqual(body["sequence"], entrada.sequence)
        self.assertEqual(body["captured_at"], entrada.captured_at)
        self.assertEqual(body["payload"]["frame_index"], 1001)
        self.assertEqual(body["payload"]["image_width"], 1920)
        self.assertEqual(body["payload"]["image_height"], 1080)
        self.assertEqual(body["payload"]["source_message_id"], entrada.message_id)

    def test_calibracao_aparece_no_evento(self):
        _, events = run_pipeline(max_frames=1)
        payload = events[0].as_dict()["payload"]
        self.assertEqual(payload["calibration_status"], "valid")
        self.assertEqual(payload["calibration_version"], "cam0-v3")


class DetectionPassthroughTest(unittest.TestCase):
    def test_pessoa_repassa_detection_id_e_bbox_do_i1(self):
        pipeline, events = run_pipeline(max_frames=1)
        originais = {d.detection_id: d.as_dict() for d in pipeline.ingestion_port.frames[0].detections}
        for person in events[0].as_dict()["payload"]["persons"]:
            original = originais[person["detection_id"]]
            self.assertEqual(person["bbox"], original["bbox"])
            self.assertEqual(person["confidence"], original["confidence"])
            for item in person["equipment"]:
                if item["detection_id"] is not None:
                    self.assertIn(item["detection_id"], originais)

    def test_toda_deteccao_aparece_exatamente_uma_vez(self):
        pipeline, events = run_pipeline()
        for indice, event in enumerate(events):
            entrada = {d.detection_id for d in pipeline.ingestion_port.frames[indice].detections}
            self.assertEqual(event.detection_ids_covered(), entrada)


class EventContentTest(unittest.TestCase):
    def test_os_tres_estados_no_mesmo_quadro(self):
        _, events = run_pipeline(max_frames=1)
        estados = {
            item["state"]
            for person in events[0].as_dict()["payload"]["persons"]
            for item in person["equipment"]
        }
        self.assertEqual(estados, {"CORRETO", "INCORRETO", "AUSENTE"})

    def test_deteccao_fraca_vai_para_ignored_detections(self):
        _, events = run_pipeline()
        ignorados = events[-1].as_dict()["payload"]["ignored_detections"]
        self.assertEqual(len(ignorados), 1)
        self.assertEqual(ignorados[0]["reason"], "low_detection_confidence")
        self.assertEqual(ignorados[0]["class"], "colete")

    def test_epi_sem_dono_vai_para_unassociated(self):
        _, events = run_pipeline(max_frames=1)
        nao_relacionados = events[0].as_dict()["payload"]["unassociated_equipment"]
        self.assertEqual(len(nao_relacionados), 1)
        self.assertEqual(nao_relacionados[0]["reason"], "below_association_threshold")

    def test_ausencia_tem_deteccao_nula(self):
        _, events = run_pipeline(max_frames=1)
        ausentes = [
            item
            for person in events[0].as_dict()["payload"]["persons"]
            for item in person["equipment"]
            if item["state"] == "AUSENTE"
        ]
        self.assertTrue(ausentes)
        for item in ausentes:
            self.assertIsNone(item["detection_id"])
            self.assertLessEqual(item["confidence"], 0.70)

    def test_uncertain_do_quadro_reflete_os_itens(self):
        _, events = run_pipeline(max_frames=1)
        payload = events[0].as_dict()["payload"]
        algum = any(item["uncertain"] for p in payload["persons"] for item in p["equipment"])
        self.assertEqual(payload["uncertain"], algum)

    def test_fonte_esgotada_retorna_none(self):
        pipeline = app.build_pipeline(max_frames=0)
        self.assertIsNone(pipeline.run_once())

    def test_quadro_sem_pessoas_publica_evento_vazio(self):
        capacete = make_detection(1, "capacete", make_bbox(468, 884, 144, 150))
        with quiet():
            event = build_message_pipeline([make_event([capacete])]).run_once()
        payload = event.as_dict()["payload"]
        self.assertEqual(payload["persons"], [])
        self.assertEqual(len(payload["unassociated_equipment"]), 1)

    def test_saida_no_console_em_json(self):
        _, events = run_pipeline(max_frames=1, as_json=True)
        self.assertEqual(len(events), 1)


class I1MessageTest(unittest.TestCase):
    """Mensagem de exemplo publicada pelo I1 (`examples/i1_detections.json`)."""

    def setUp(self):
        self.message = json.loads(EXAMPLE_I1.read_text(encoding="utf-8"))

    def test_bbox_do_i1_e_convertida_para_origem_inferior(self):
        frame = DetectionFrame.from_event(self.message)
        pessoa = {d.detection_id: d for d in frame.detections}[0]
        # [412, 180, 598, 702] com altura 720 -> y_min = 720 - 702, y_max = 720 - 180
        self.assertEqual(
            (pessoa.bbox.x_min, pessoa.bbox.y_min, pessoa.bbox.x_max, pessoa.bbox.y_max),
            (412.0, 18.0, 598.0, 540.0),
        )
        self.assertEqual(pessoa.bbox.to_image_list(720), [412.0, 180.0, 598.0, 702.0])

    def test_exemplo_do_i1_gera_conformidade(self):
        sent = []
        event = build_message_pipeline([json.dumps(self.message)], sent=sent).run_once()
        body = event.as_dict()

        self.assertEqual(body["source_id"], "cam0")
        self.assertEqual(body["session_id"], self.message["session_id"])
        self.assertEqual(body["sequence"], 42)
        self.assertEqual(body["captured_at"], self.message["captured_at"])
        self.assertEqual(body["payload"]["frame_index"], 42)
        self.assertEqual(body["payload"]["source_message_id"], self.message["message_id"])

        person = body["payload"]["persons"][0]
        self.assertEqual(person["detection_id"], 0)
        itens = {item["equipment_item"]: item for item in person["equipment"]}
        self.assertEqual(itens["capacete"]["state"], "CORRETO")
        self.assertEqual(itens["capacete"]["detection_id"], 1)
        self.assertEqual(itens["colete"]["state"], "CORRETO")
        self.assertEqual(itens["colete"]["detection_id"], 2)

        self.assertEqual(len(sent), 1)
        topic, key, value = sent[0]
        self.assertEqual(topic, "ods.i9.ppe_compliance")
        self.assertEqual(key, "cam0")
        self.assertEqual(json.loads(value)["message_id"], body["message_id"])

    def test_mensagens_invalidas_sao_rejeitadas_sem_parar_o_consumo(self):
        schema_errado = dict(self.message, schema="ods.i2.tracks")
        sem_bbox = json.loads(json.dumps(self.message))
        del sem_bbox["payload"]["detections"][0]["bbox"]
        duplicado = json.loads(json.dumps(self.message))
        duplicado["payload"]["detections"][1]["detection_id"] = 0

        adapter = MessageIngestionAdapter(["{nao e json", schema_errado, sem_bbox, duplicado, self.message])
        frame = adapter.get_next_event()
        self.assertEqual(frame.sequence, 42)
        self.assertEqual(len(adapter.rejected), 4)
        self.assertIsNone(adapter.get_next_event())

    def test_bbox_invertida_e_rejeitada(self):
        invalida = json.loads(json.dumps(self.message))
        invalida["payload"]["detections"][0]["bbox"] = [598, 180, 412, 702]
        with self.assertRaises(ValueError):
            DetectionFrame.from_event(invalida)


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
            def get_calibration(self, source_id):
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
        estados = [item["state"] for item in payload["persons"][0]["equipment"]]
        self.assertIn("CORRETO", estados)

    def test_calibracao_do_i3_por_mensagem(self):
        calibracao = make_calibration(source_id="CAM-01").raw
        mensagem = {
            "message_type": "event",
            "schema": "ods.i3.calibration",
            "schema_version": SCHEMA_VERSION,
            "producer": "I3",
            "source_id": "CAM-01",
            "payload": calibracao,
        }
        pessoa = make_detection(0, "pessoa", PERSON_BOX)
        with quiet():
            event = build_message_pipeline([make_event([pessoa])], calibrations=[mensagem]).run_once()
        self.assertEqual(event.calibration.status, "valid")
        self.assertEqual(event.calibration.version, "cam-01-v3")

    def test_calibracao_sem_homografia_e_aceita(self):
        adapter = MessageCalibrationAdapter()
        calibration = adapter.on_message(
            {
                "schema": "ods.i3.calibration",
                "source_id": "cam0",
                "payload": {"calibration_version": "cam0-v1", "intrinsics": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
            }
        )
        self.assertIsNone(calibration.homography)
        self.assertEqual(adapter.get_calibration("cam0").calibration_version, "cam0-v1")

    def test_adapter_devolve_apenas_a_sua_camera(self):
        adapter = MockCalibrationAdapter()
        self.assertIsNone(adapter.get_calibration("CAM-99"))


if __name__ == "__main__":
    unittest.main()
