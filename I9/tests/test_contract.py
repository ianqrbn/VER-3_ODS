"""Testes de contrato: `ods.i1.detections` (com `ods.i3.calibration`) -> `ods.i9.ppe_compliance`."""

from __future__ import annotations

import json
import re
import unittest
import uuid

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

# Especificação de interfaces 1.0, seção 6, tabela de `ods.i9.ppe_compliance`
CAMPOS_PAYLOAD = (
    "frame_index",
    "detection_id",
    "bbox",
    "calibrated",
    "catalog_version",
    "items",
    "uncertain",
)
CAMPOS_ITEM_OBRIGATORIOS = ("equipment_item", "compliance", "confidence")
CAMPOS_ITEM = CAMPOS_ITEM_OBRIGATORIOS + ("bbox",)
COMPLIANCE = ("CORRECT", "INCORRECT", "ABSENT")
DATETIME_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _e_bbox(valor) -> bool:
    return (
        isinstance(valor, list)
        and len(valor) == 4
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in valor)
    )


def _e_uuid(valor) -> bool:
    try:
        uuid.UUID(str(valor))
    except ValueError:
        return False
    return True


def erros_de_contrato(mensagem) -> list:
    """Confere uma mensagem contra o envelope EV-SINAL e a tabela do payload."""
    erros = []
    for campo in CAMPOS_ENVELOPE:
        if campo not in mensagem:
            erros.append(f"envelope sem {campo}")
    if erros:
        return erros
    if mensagem["message_type"] != "event":
        erros.append("message_type")
    if mensagem["schema"] != COMPLIANCE_SCHEMA or mensagem["schema_version"] != SCHEMA_VERSION:
        erros.append("schema/schema_version")
    if mensagem["producer"] != "I9":
        erros.append("producer")
    if not _e_uuid(mensagem["message_id"]):
        erros.append("message_id não é UUID")
    if not DATETIME_UTC.match(str(mensagem["published_at"])):
        erros.append("published_at fora do ISO 8601 UTC")
    for campo in ("source_id", "artifact_version"):
        if not isinstance(mensagem[campo], str) or not mensagem[campo]:
            erros.append(f"{campo} vazio")

    payload = mensagem["payload"]
    faltando = [c for c in CAMPOS_PAYLOAD if c not in payload]
    sobrando = [c for c in payload if c not in CAMPOS_PAYLOAD]
    erros += [f"payload sem {c}" for c in faltando]
    erros += [f"payload com campo fora do contrato: {c}" for c in sobrando]
    if faltando:
        return erros
    for campo in ("frame_index", "detection_id"):
        valor = payload[campo]
        if not isinstance(valor, int) or isinstance(valor, bool) or valor < 0:
            erros.append(f"{campo} não é inteiro >= 0")
    if not _e_bbox(payload["bbox"]):
        erros.append("bbox não é [x_min, y_min, x_max, y_max]")
    for campo in ("calibrated", "uncertain"):
        if not isinstance(payload[campo], bool):
            erros.append(f"{campo} não é boolean")
    if not isinstance(payload["catalog_version"], str) or not payload["catalog_version"]:
        erros.append("catalog_version não é string")
    if not isinstance(payload["items"], list):
        return erros + ["items não é array"]
    for i, item in enumerate(payload["items"]):
        erros += [f"items[{i}] sem {c}" for c in CAMPOS_ITEM_OBRIGATORIOS if c not in item]
        erros += [f"items[{i}] com campo fora do contrato: {c}" for c in item if c not in CAMPOS_ITEM]
        if item.get("compliance") not in COMPLIANCE:
            erros.append(f"items[{i}].compliance fora do enum")
        confianca = item.get("confidence")
        if not isinstance(confianca, (int, float)) or not 0.0 <= confianca <= 1.0:
            erros.append(f"items[{i}].confidence fora de 0.0–1.0")
        if "bbox" in item and not _e_bbox(item["bbox"]):
            erros.append(f"items[{i}].bbox inválida")
    return erros


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
            mensagens = event.messages()
            self.assertEqual(len(mensagens), len(event.relations))
            for body in mensagens:
                self.assertEqual(erros_de_contrato(body), [])
                self.assertEqual(body["schema"], "ods.i9.ppe_compliance")
                self.assertEqual(body["artifact_version"], default_policy().artifact_version)

    def test_uma_mensagem_por_pessoa_com_a_pessoa_do_i1(self):
        pipeline, events = run_pipeline(max_frames=1)
        entrada = {d.detection_id: d.raw for d in pipeline.ingestion_port.frames[0].detections}
        for relation, body in zip(events[0].relations, events[0].messages()):
            payload = body["payload"]
            self.assertEqual(payload["detection_id"], relation.person.detection_id)
            self.assertEqual(payload["bbox"], entrada[payload["detection_id"]]["bbox"])
            for item, avaliacao in zip(payload["items"], relation.equipment):
                self.assertEqual(item["compliance"], avaliacao.state.compliance)
                if avaliacao.detection is None:
                    self.assertNotIn("bbox", item)
                else:
                    self.assertEqual(item["bbox"], entrada[avaliacao.detection.detection_id]["bbox"])

    def test_message_id_e_unico_por_mensagem(self):
        _, events = run_pipeline()
        ids = [m["message_id"] for e in events for m in e.messages()]
        self.assertEqual(len(set(ids)), len(ids))
        # o mesmo evento gera sempre os mesmos ids (republicar não duplica)
        self.assertEqual(
            [m["message_id"] for m in events[0].messages()],
            [m["message_id"] for m in events[0].messages()],
        )

    def test_evento_e_serializavel_em_json(self):
        _, events = run_pipeline(max_frames=1)
        json.dumps(events[0].frame_report(), ensure_ascii=False)
        for body in events[0].messages():
            json.dumps(body, ensure_ascii=False)

    def test_chave_do_quadro_e_repassada_do_i1(self):
        pipeline, events = run_pipeline(max_frames=1)
        entrada = pipeline.ingestion_port.frames[0]
        body = events[0].frame_report()
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
        payload = events[0].frame_report()["payload"]
        self.assertEqual(payload["calibration_status"], "valid")
        self.assertEqual(payload["calibration_version"], "cam0-v3")


class DetectionPassthroughTest(unittest.TestCase):
    def test_pessoa_repassa_detection_id_e_bbox_do_i1(self):
        pipeline, events = run_pipeline(max_frames=1)
        originais = {d.detection_id: d.as_dict() for d in pipeline.ingestion_port.frames[0].detections}
        for person in events[0].frame_report()["payload"]["persons"]:
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
            for person in events[0].frame_report()["payload"]["persons"]
            for item in person["equipment"]
        }
        self.assertEqual(estados, {"CORRETO", "INCORRETO", "AUSENTE"})

    def test_deteccao_fraca_vai_para_ignored_detections(self):
        _, events = run_pipeline()
        ignorados = events[-1].frame_report()["payload"]["ignored_detections"]
        self.assertEqual(len(ignorados), 1)
        self.assertEqual(ignorados[0]["reason"], "low_detection_confidence")
        self.assertEqual(ignorados[0]["class"], "colete")

    def test_epi_sem_dono_vai_para_unassociated(self):
        _, events = run_pipeline(max_frames=1)
        nao_relacionados = events[0].frame_report()["payload"]["unassociated_equipment"]
        self.assertEqual(len(nao_relacionados), 1)
        self.assertEqual(nao_relacionados[0]["reason"], "below_association_threshold")

    def test_ausencia_tem_deteccao_nula(self):
        _, events = run_pipeline(max_frames=1)
        ausentes = [
            item
            for person in events[0].frame_report()["payload"]["persons"]
            for item in person["equipment"]
            if item["state"] == "AUSENTE"
        ]
        self.assertTrue(ausentes)
        for item in ausentes:
            self.assertIsNone(item["detection_id"])
            self.assertLessEqual(item["confidence"], 0.70)

    def test_uncertain_do_quadro_reflete_os_itens(self):
        _, events = run_pipeline(max_frames=1)
        payload = events[0].frame_report()["payload"]
        algum = any(item["uncertain"] for p in payload["persons"] for item in p["equipment"])
        self.assertEqual(payload["uncertain"], algum)

    def test_fonte_esgotada_retorna_none(self):
        pipeline = app.build_pipeline(max_frames=0)
        self.assertIsNone(pipeline.run_once())

    def test_quadro_sem_pessoas_publica_evento_vazio(self):
        capacete = make_detection(1, "capacete", make_bbox(468, 884, 144, 150))
        with quiet():
            event = build_message_pipeline([make_event([capacete])]).run_once()
        payload = event.frame_report()["payload"]
        self.assertEqual(payload["persons"], [])
        self.assertEqual(len(payload["unassociated_equipment"]), 1)
        # o contrato é uma mensagem por pessoa: sem pessoa, nada é publicado
        self.assertEqual(event.messages(), [])

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
        body = event.frame_report()

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
        publicada = json.loads(value)
        self.assertEqual(erros_de_contrato(publicada), [])
        self.assertEqual(publicada["message_id"], event.messages()[0]["message_id"])
        self.assertEqual(publicada["sequence"], 42)
        payload = publicada["payload"]
        self.assertEqual(payload["frame_index"], 42)
        self.assertEqual(payload["detection_id"], 0)
        self.assertEqual(payload["bbox"], [412, 180, 598, 702])
        # sem mensagem do I3 neste pipeline: operou em pixels
        self.assertIs(payload["calibrated"], False)
        self.assertEqual(payload["catalog_version"], "local-default-1.0")
        self.assertEqual(
            payload["items"],
            [
                {"equipment_item": "capacete", "compliance": "CORRECT",
                 "confidence": itens["capacete"]["confidence"], "bbox": [450, 182, 540, 255]},
                {"equipment_item": "colete", "compliance": "CORRECT",
                 "confidence": itens["colete"]["confidence"], "bbox": [425, 290, 585, 510]},
            ],
        )

    def test_exemplo_com_calibracao_do_i3_marca_calibrated(self):
        calibracao = (ROOT / "examples" / "i3_calibration.json").read_text(encoding="utf-8")
        sent = []
        build_message_pipeline([json.dumps(self.message)], [calibracao], sent=sent).run_once()
        publicada = json.loads(sent[0][2])
        self.assertEqual(erros_de_contrato(publicada), [])
        self.assertIs(publicada["payload"]["calibrated"], True)

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
            payload = pipeline.run_once().frame_report()["payload"]
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

    def test_calibracao_no_formato_do_contrato(self):
        mensagem = json.loads((ROOT / "examples" / "i3_calibration.json").read_text(encoding="utf-8"))
        calibration = MessageCalibrationAdapter().on_message(mensagem)
        # versão vem do artifact_version do envelope; matriz de homography_px_to_m
        self.assertEqual(calibration.calibration_version, "cal-cam0-1")
        self.assertEqual(
            calibration.homography,
            tuple(tuple(linha) for linha in mensagem["payload"]["homography_px_to_m"]),
        )
        self.assertEqual(calibration.space_id, "obra-civil")
        self.assertEqual(calibration.meters_per_unit, 1.0)

    def test_calibracao_sem_versao_e_rejeitada(self):
        adapter = MessageCalibrationAdapter()
        mensagem = json.loads((ROOT / "examples" / "i3_calibration.json").read_text(encoding="utf-8"))
        del mensagem["artifact_version"]
        self.assertIsNone(adapter.on_message(mensagem))
        self.assertIn("artifact_version", adapter.rejected[0][1])

    def test_adapter_devolve_apenas_a_sua_camera(self):
        adapter = MockCalibrationAdapter()
        self.assertIsNone(adapter.get_calibration("CAM-99"))


if __name__ == "__main__":
    unittest.main()
