"""Testes do PPE_CATALOG do A5: parsing, política derivada, registro e Kafka."""

from __future__ import annotations

import hashlib
import io
import json
import unittest

from tests.helpers import (
    PERSON_BOX,
    ROOT,
    default_policy,
    make_bbox,
    make_calibration,
    make_detection,
    make_frame,
    quiet,
)
import main as app
from src.adapters.catalog_adapters import CatalogLoader, RegistryClient
from src.adapters.kafka_adapters import (
    KafkaArtifactAdapter,
    KafkaCalibrationAdapter,
    KafkaI9Service,
    KafkaIngestionAdapter,
    KafkaPublisherAdapter,
)
from src.core.calibration import CalibrationStore
from src.core.inference import RelationInferenceModule
from src.core.pairing import PairingModule
from src.domain.body_zones import BodyZone
from src.domain.catalog import ArtifactPublished, PpeCatalog
from src.domain.models import RelationalState
from tests.test_kafka import FakeConsumer, FakeMessage, FakeProducer, i1_message, outputs

CONTENT = json.loads((ROOT / "examples" / "a5_ppe_catalog.json").read_text(encoding="utf-8"))
ANNOUNCE = json.loads((ROOT / "examples" / "a5_artifact_published.json").read_text(encoding="utf-8"))
BODY = json.dumps(CONTENT).encode("utf-8")


def catalog() -> PpeCatalog:
    return PpeCatalog.from_content(CONTENT, "ppe-a5", "ppe-a5-3")


def announce(**payload) -> dict:
    data = json.loads(json.dumps(ANNOUNCE))
    data["payload"]["hash_sha256"] = hashlib.sha256(BODY).hexdigest()
    data["payload"].update(payload)
    return data


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeOpener:
    def __init__(self, body: bytes = BODY, error: Exception | None = None):
        self.body = body
        self.error = error
        self.urls = []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        if self.error:
            raise self.error
        return FakeResponse(self.body)


def loader(opener=None, base_url="http://a5:8000") -> CatalogLoader:
    return CatalogLoader(RegistryClient(base_url, opener=opener or FakeOpener()))


class CatalogParsingTest(unittest.TestCase):
    def test_catalogo_do_a5(self):
        cat = catalog()
        self.assertEqual(len(cat.items), 7)
        self.assertEqual(cat.required_by_zone["galpao-solda"], ("capacete", "luvas", "oculos"))
        # união das zonas, na ordem do catálogo
        self.assertEqual(cat.required_items(), ("capacete", "colete", "luvas", "oculos"))

    def test_item_obrigatorio_fora_do_catalogo_e_rejeitado(self):
        data = json.loads(json.dumps(CONTENT))
        data["required"][0]["items"].append("cinto")
        with self.assertRaisesRegex(ValueError, "cinto"):
            PpeCatalog.from_content(data)

    def test_item_duplicado_e_rejeitado(self):
        data = json.loads(json.dumps(CONTENT))
        data["items"].append(dict(data["items"][0]))
        with self.assertRaisesRegex(ValueError, "duplicado"):
            PpeCatalog.from_content(data)

    def test_anuncio_de_artefato(self):
        artifact = ArtifactPublished.from_event(ANNOUNCE)
        self.assertEqual(artifact.kind, "PPE_CATALOG")
        self.assertEqual(artifact.artifact_version, "ppe-a5-3")
        self.assertEqual(artifact.owner, "A5")


class PolicyFromCatalogTest(unittest.TestCase):
    def setUp(self):
        self.policy = default_policy().with_catalog(catalog())

    def test_ids_do_a5_viram_classes_canonicas(self):
        self.assertEqual(
            self.policy.class_order,
            ("bota", "capacete", "colete", "luvas", "mascara", "oculos", "protetor_auricular"),
        )
        self.assertEqual(self.policy.catalog_version, "ppe-a5-3")

    def test_obrigatorios_sao_a_uniao_das_zonas(self):
        self.assertEqual(self.policy.required_classes(), ("capacete", "colete", "luvas", "oculos"))

    def test_class_aliases_casam_com_as_classes_do_i1(self):
        self.assertEqual(self.policy.canonical_for("hard hat"), "capacete")
        self.assertEqual(self.policy.canonical_for("Gloves"), "luvas")
        self.assertEqual(self.policy.canonical_for("earmuffs"), "protetor_auricular")
        # o próprio id também é aceito como classe
        self.assertEqual(self.policy.canonical_for("protetor_auricular"), "protetor_auricular")

    def test_zona_do_corpo_vem_do_i9(self):
        self.assertIs(self.policy.rules["luvas"].zone, BodyZone.HANDS)
        self.assertIs(self.policy.rules["bota"].zone, BodyZone.FEET)
        self.assertIs(self.policy.rules["oculos"].zone, BodyZone.HEAD)

    def test_parametros_do_motor_sao_preservados(self):
        base = default_policy()
        self.assertEqual(self.policy.confidence, base.confidence)
        self.assertEqual(self.policy.association, base.association)

    def test_item_sem_zona_conhecida_nao_e_avaliado(self):
        data = json.loads(json.dumps(CONTENT))
        data["items"].append({"equipment_item": "cinto", "name": "Cinto", "class_aliases": ["harness"]})
        policy = default_policy().with_catalog(PpeCatalog.from_content(data))
        self.assertEqual(policy.unsupported_items, ("cinto",))
        self.assertNotIn("cinto", policy.rules)

    def test_alias_igual_a_classe_de_pessoa_e_rejeitado(self):
        data = json.loads(json.dumps(CONTENT))
        data["items"][0]["class_aliases"].append("person")
        with self.assertRaisesRegex(ValueError, "pessoa"):
            default_policy().with_catalog(PpeCatalog.from_content(data))

    def test_saida_usa_os_ids_do_a5(self):
        luva = make_detection(12, "glove", make_bbox(430, 400, 60, 60))
        oculos = make_detection(13, "goggles", make_bbox(520, 900, 50, 25))
        bota = make_detection(14, "boots", make_bbox(470, 268, 120, 50))
        capacete = make_detection(10, "hard hat", make_bbox(468, 884, 144, 150))
        pessoa = make_detection(1, "pessoa", PERSON_BOX)

        store = CalibrationStore(self.policy.calibration)
        store.upsert(make_calibration())
        pairing = PairingModule(self.policy, store).pair(
            make_frame([pessoa, capacete, luva, oculos, bota])
        )
        avaliacao = RelationInferenceModule(self.policy).infer(pairing)[0]
        estados = {e.canonical_class: e.state for e in avaliacao.equipment}

        self.assertEqual(estados["capacete"], RelationalState.CORRETO)
        self.assertEqual(estados["luvas"], RelationalState.CORRETO)
        self.assertEqual(estados["oculos"], RelationalState.CORRETO)
        self.assertEqual(estados["bota"], RelationalState.CORRETO)
        self.assertEqual(estados["colete"], RelationalState.AUSENTE)
        # mascara e protetor não são exigidos em nenhuma zona e não foram detectados
        self.assertNotIn("mascara", estados)


class RegistryTest(unittest.TestCase):
    def test_uri_de_registro_usa_a_base_do_a5(self):
        client = RegistryClient("http://a5:8000/")
        url = client.resolve(ArtifactPublished.from_event(ANNOUNCE))
        self.assertEqual(url, "http://a5:8000/registro/ppe-a5/3")

    def test_uri_de_registro_sem_base_configurada_falha(self):
        with self.assertRaisesRegex(ValueError, "A5_REGISTRY_BASE_URL"):
            RegistryClient("").resolve(ArtifactPublished.from_event(ANNOUNCE))

    def test_uri_http_e_usada_diretamente(self):
        artifact = ArtifactPublished.from_event(announce(uri="https://a5.local/x/3"))
        self.assertEqual(RegistryClient("").resolve(artifact), "https://a5.local/x/3")

    def test_carrega_e_confere_hash_dos_bytes(self):
        opener = FakeOpener()
        cat = loader(opener).on_message(announce())
        self.assertEqual(cat.artifact_version, "ppe-a5-3")
        self.assertEqual(opener.urls, ["http://a5:8000/registro/ppe-a5/3"])

    def test_aceita_hash_do_json_canonico(self):
        canonico = json.dumps(CONTENT, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        mensagem = announce(hash_sha256=hashlib.sha256(canonico.encode()).hexdigest())
        self.assertIsNotNone(loader().on_message(mensagem))

    def test_aceita_conteudo_envolvido_em_content(self):
        corpo = json.dumps({"artifact_id": "ppe-a5", "content": CONTENT}).encode()
        mensagem = announce(hash_sha256=hashlib.sha256(corpo).hexdigest())
        self.assertIsNotNone(loader(FakeOpener(corpo)).on_message(mensagem))

    def test_hash_divergente_e_rejeitado(self):
        carregador = loader()
        self.assertIsNone(carregador.on_message(announce(hash_sha256="0" * 64)))
        self.assertIn("hash_sha256", carregador.rejected[0][1])

    def test_registro_indisponivel_e_rejeitado(self):
        carregador = loader(FakeOpener(error=OSError("conexão recusada")))
        self.assertIsNone(carregador.on_message(announce()))
        self.assertEqual(len(carregador.rejected), 1)

    def test_outros_artefatos_e_outros_donos_sao_ignorados(self):
        carregador = loader()
        self.assertIsNone(carregador.on_message(announce(kind="ROUTING")))
        self.assertIsNone(carregador.on_message(announce(owner="A7")))
        self.assertEqual(carregador.rejected, [])


class PipelineCatalogTest(unittest.TestCase):
    def test_main_com_catalogo_avalia_a_uniao_das_zonas(self):
        pipeline = app.build_pipeline(
            input_path=str(ROOT / "examples" / "i1_detections.json"),
            catalog_path=str(ROOT / "examples" / "a5_ppe_catalog.json"),
        )
        with quiet():
            body = pipeline.run_once().as_dict()
        itens = {i["equipment_item"]: i for i in body["payload"]["persons"][0]["equipment"]}
        self.assertEqual(set(itens), {"capacete", "colete", "luvas", "oculos"})
        self.assertEqual(itens["capacete"]["state"], "CORRETO")
        self.assertEqual(itens["luvas"]["state"], "AUSENTE")

    def test_catalogo_invalido_mantem_a_politica_anterior(self):
        pipeline = app.build_pipeline()
        anterior = pipeline.policy
        data = json.loads(json.dumps(CONTENT))
        data["items"][0]["class_aliases"].append("pessoa")
        with self.assertRaises(ValueError):
            pipeline.apply_catalog(PpeCatalog.from_content(data))
        self.assertIs(pipeline.policy, anterior)
        self.assertIs(pipeline.pairing_module.policy, anterior)


class KafkaCatalogTest(unittest.TestCase):
    def test_servico_aplica_o_catalogo_do_topico(self):
        producer = FakeProducer()
        ingestion = KafkaIngestionAdapter(FakeConsumer([i1_message(1)]))
        calibration = KafkaCalibrationAdapter(FakeConsumer())
        artifacts = KafkaArtifactAdapter(
            FakeConsumer([FakeMessage(announce(), topic="ods.artifact.published")]), loader()
        )
        publisher = KafkaPublisherAdapter(producer)
        pipeline = app.build_pipeline(ingestion=ingestion, calibration=calibration, output=publisher)
        service = KafkaI9Service(pipeline, ingestion, calibration, publisher, artifacts)

        with self.assertLogs("i9.kafka", level="INFO"):
            service.run(max_frames=1)

        body = json.loads(outputs(producer)[0]["value"])
        self.assertEqual(body["payload"]["catalog_version"], "ppe-a5-3")
        itens = {i["equipment_item"] for i in body["payload"]["persons"][0]["equipment"]}
        self.assertEqual(itens, {"capacete", "colete", "luvas", "oculos"})


if __name__ == "__main__":
    unittest.main()
