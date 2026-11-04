# I9 · Inferência relacional pessoa–EPI

Verificação **geométrica** (sem modelo de visão computacional) do uso de EPI por
pessoa, a partir das detecções do **I1** e da calibração do **I3**
(arquitetura 6c).

Para cada pessoa e para cada classe de EPI definida na política da aplicação, o
componente emite um estado relacional — `CORRETO`, `INCORRETO` ou `AUSENTE` —
com confiança e a sinalização `uncertain`, publicando `ods.i9.ppe_compliance`
para o **S2** e o **A5**.

O I9 é um verificador **especializado em pessoas**: a anatomia (cabeça, tronco,
mãos) e sua geometria são conhecimento do motor. A aplicação configura apenas
*quais* EPIs existem, *quais* são obrigatórios e *em qual zona* cada um deve ser
usado.

## Execução

```bash
cd I9
python3 main.py                                        # 3 quadros simulados (mock)
python3 main.py --input examples/i1_detections.json --json   # mensagens reais do I1
python3 main.py --input quadros.jsonl --calibration calib.jsonl
python3 main.py --catalog examples/a5_ppe_catalog.json   # usa o PPE_CATALOG do A5
python3 -m unittest discover -s tests -t .
```

`--input` e `--calibration` aceitam um objeto JSON, uma lista JSON ou JSONL.
Sem dependências externas: apenas a biblioteca padrão do Python 3.10+. O modo
`--kafka` exige `confluent-kafka` (`requirements-kafka.txt`); os testes usam
clientes falsos e não precisam dele.

## Fluxo

```text
I1  ods.i1.detections  ──┐
                         ├─► I9Pipeline ─► PairingModule ─► RelationInferenceModule ─► ods.i9.ppe_compliance ─► S2, A5
I3  ods.i3.calibration ──┘                   (associação)      (estado + confiança)
```

* `I9Pipeline` (`src/core/pipeline.py`) orquestra **um quadro estático** por
  vez, sem estado acumulado: o **cruzamento temporal é do S2**, que casa a pessoa
  inferida pelo I9 com o rastro do I2 pelo `detection_id` + chave do quadro
  (`source_id`, `session_id`, `frame_index`).
* `PairingModule` (`src/core/pairing.py`) associa EPIs a pessoas de forma
  **um-para-um** (EPIs são individuais).
* `RelationInferenceModule` (`src/core/inference.py`) decide o estado relacional
  e o `uncertain`.
* `CalibrationStore` (`src/core/calibration.py`) valida e guarda a calibração do
  I3 por `source_id`.
* `body_zones.py` (`src/domain/body_zones.py`) guarda a geometria do corpo humano.
* A política fica **fora do código**, em `config/policy.json`.

### Adaptadores

| Porta | Mock | Mensagens reais (`src/adapters/message_adapters.py`) |
|---|---|---|
| ingestão (I1) | `MockIngestionAdapter` | `MessageIngestionAdapter(mensagens)` |
| calibração (I3) | `MockCalibrationAdapter` | `MessageCalibrationAdapter` (`on_message` como callback) |
| saída | `MockConsoleOutputAdapter` | `MessagePublisherAdapter(send)` |

No modo `--kafka`, as mesmas portas são atendidas por `KafkaIngestionAdapter`,
`KafkaCalibrationAdapter` e `KafkaPublisherAdapter` (ver seção Kafka).

Os adaptadores de mensagem não dependem do transporte: o consumidor do B3
(Kafka) entrega o corpo de cada mensagem (`dict`, `str` ou `bytes` JSON) e o
produtor expõe `send(topic, key, value)`. A chave publicada é o `source_id`, para
preservar a ordem dos quadros de cada câmera. Mensagens inválidas são
registradas em `rejected` sem interromper o consumo.

## Kafka (barramento B3)

```bash
pip install -r requirements-kafka.txt        # confluent-kafka (só para o modo Kafka)
docker compose up -d kafka kafka-init        # só o broker em localhost:9092 + tópicos
python3 main.py --kafka                      # serviço contínuo do I9
# ou tudo em containers: docker compose up -d --build (I9 incluso, sem o passo acima)

# em outro terminal
python3 tools/kafka_cli.py send examples/i3_calibration.json
python3 tools/kafka_cli.py send examples/i1_detections.json
python3 tools/kafka_cli.py tail ods.i9.ppe_compliance
```

| Tópico | Papel | Chave | Observação |
|---|---|---|---|
| `ods.i1.detections` | consumido | `source_id` | grupo `ods-i9`, commit manual |
| `ods.i3.calibration` | consumido | `source_id` | **compactado**; relido desde o início a cada partida |
| `ods.artifact.published` | consumido | `artifact_id` | **compactado**; só `PPE_CATALOG` do A5; relido a cada partida |
| `ods.i9.ppe_compliance` | publicado | `source_id` | `acks=all`, produtor idempotente |
| `ods.i9.dlq` | publicado | original | mensagens inválidas + headers `error`, `source_*` |

Garantias (`src/adapters/kafka_adapters.py`):

* **at-least-once** — o offset do quadro do I1 só é confirmado depois que o
  broker confirma a entrega da saída. Se o I9 cair no meio, o quadro é
  reprocessado; o resultado é o mesmo e o S2 descarta a duplicata pela chave do
  quadro. Falha de entrega encerra o serviço **sem** confirmar o offset;
* mensagem inválida vai para o DLQ, tem o offset confirmado e não trava o consumo;
* erro transitório do consumidor é registrado; erro fatal encerra o serviço;
* `SIGINT`/`SIGTERM` encerram o laço de forma limpa;
* chave = `source_id`: os quadros de uma câmera ficam na mesma partição, em ordem.

Configuração por variáveis de ambiente (defaults **provisórios**, a confirmar com o B3):

| Variável | Padrão |
|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` |
| `I9_KAFKA_GROUP_ID` | `ods-i9` |
| `I9_TOPIC_DETECTIONS` / `I9_TOPIC_CALIBRATION` / `I9_TOPIC_COMPLIANCE` | nomes dos schemas |
| `I9_TOPIC_DLQ` | `ods.i9.dlq` (vazio desliga) |
| `I9_TOPIC_ARTIFACTS` | `ods.artifact.published` |
| `A5_REGISTRY_BASE_URL` | vazio (obrigatório para `uri` `registry://`) |
| `I9_CATALOG_OWNER` | `A5` (vazio aceita qualquer dono) |
| `I9_AUTO_OFFSET_RESET` | `latest` (sem offset salvo, começa do quadro atual) |
| `I9_DELIVERY_TIMEOUT_S` / `I9_POLL_TIMEOUT_S` / `I9_CALIBRATION_WARMUP_S` | `10` / `1` / `3` |
| `KAFKA_SECURITY_PROTOCOL`, `KAFKA_SASL_MECHANISM`, `KAFKA_SASL_USERNAME`, `KAFKA_SASL_PASSWORD`, `KAFKA_SSL_CA_LOCATION` | `PLAINTEXT` / vazio |

### VM no Compute Engine (Google Cloud)

`deploy/gce/deploy.sh` cria uma VM Debian 12, instala o Docker, copia o I9 (sem o
dataset) e roda `docker compose up -d --build`. A VM tem hora de término
(`TERMINATION_TIME`, padrão `2026-11-07T00:00:00-03:00`): nesse momento o
Compute Engine a exclui junto com o disco.

```bash
gcloud auth login && gcloud config set project SEU_PROJETO
./deploy/gce/deploy.sh                                   # Kafka acessível só dentro da VM
ALLOWED_CIDR=200.10.20.30/32 ./deploy/gce/deploy.sh      # libera a 9092 para essa faixa
./deploy/gce/teardown.sh                                 # exclui a VM e a regra de firewall
```

Com `ALLOWED_CIDR`, o broker anuncia o IP externo da VM (`KAFKA_EXTERNAL_HOST`
no `.env`) e os outros componentes usam `KAFKA_BOOTSTRAP_SERVERS=<ip>:9092`. O
listener é `PLAINTEXT`, sem autenticação: libere só IPs conhecidos.

## Contratos

### Entrada — detecções (I1)

```json
{
  "message_type": "event",
  "message_id": "a8f5f167-99b4-4d2b-8b1e-6c9a2e4f1d3b",
  "schema": "ods.i1.detections",
  "schema_version": "1.0",
  "producer": "I1",
  "published_at": "2026-10-18T22:01:10.145Z",
  "captured_at": "2026-10-18T22:01:10.110Z",
  "source_id": "cam0",
  "session_id": "9c2a1f3e-4d5b-4c6a-9e8f-0a1b2c3d4e5f",
  "sequence": 42,
  "artifact_version": "app-epi-1.0.0",
  "payload": {
    "frame_index": 42,
    "image_width": 1280,
    "image_height": 720,
    "detections": [
      { "detection_id": 0, "class": "pessoa",   "confidence": 0.9412, "bbox": [412, 180, 598, 702] },
      { "detection_id": 1, "class": "capacete", "confidence": 0.9604, "bbox": [450, 182, 540, 255] },
      { "detection_id": 2, "class": "colete",   "confidence": 0.9318, "bbox": [425, 290, 585, 510] }
    ]
  }
}
```

* `bbox` é `[x1, y1, x2, y2]` em pixels com origem no canto **superior**
  esquerdo. No parsing ela é convertida para a convenção interna do motor
  (origem **inferior**, usando `image_height`), para que a cabeça fique em `v` alto.
* Obrigatórios: `schema`, `source_id`, `payload.image_width`,
  `payload.image_height` e, por detecção, `detection_id`, `class`, `confidence`
  (0–1) e `bbox`. `detection_id` duplicado no quadro invalida a mensagem.

### Entrada — calibração (I3)

```json
{
  "message_type": "event",
  "schema": "ods.i3.calibration",
  "schema_version": "1.0",
  "producer": "I3",
  "source_id": "cam0",
  "payload": {
    "calibration_version": "cam0-v3",
    "valid_from": "2026-09-23T13:58:00.000Z",
    "homography": [[0.004, -0.0002, 0.85], [0.0001, -0.0042, 1.15], [-0.0000009, 0.0000021, 1.0]],
    "reference_frame": { "space_id": "obra-civil", "origin": "0,0", "axes": "x_direita,y_frente", "unit": "m" },
    "reprojection_rms_cm": 1.8,
    "holdout_points": 6
  }
}
```

A calibração é indexada pelo `source_id` do envelope (com `payload.source_id`
ou `payload.camera_id` como alternativa). `homography` é **opcional**: sem ela o
I9 funciona normalmente, apenas sem o corte métrico de alcance. Demais campos
(parâmetros intrínsecos, distorção) são preservados. A homografia é usada como
**corte de alcance** e como auditoria, não como critério de posição.

### Saída — conformidade de EPI (I9, envelope EV-SINAL)

Contrato `ods.i9.ppe_compliance` da Especificação de interfaces 1.0 (seção 6):
**uma mensagem por pessoa detectada no quadro**.

```json
{
  "message_type": "event",
  "message_id": "9f868655-5526-412d-8c23-42c7fdc81a88",
  "schema": "ods.i9.ppe_compliance",
  "schema_version": "1.0",
  "producer": "I9",
  "published_at": "2026-11-04T14:50:11.798Z",
  "captured_at": "2026-10-18T22:01:10.110Z",
  "source_id": "cam0",
  "session_id": "9c2a1f3e-4d5b-4c6a-9e8f-0a1b2c3d4e5f",
  "sequence": 42,
  "artifact_version": "i9-geom-default-1.0",
  "payload": {
    "frame_index": 42,
    "detection_id": 0,
    "bbox": [412, 180, 598, 702],
    "calibrated": true,
    "catalog_version": "local-default-1.0",
    "items": [
      { "equipment_item": "capacete", "compliance": "CORRECT", "confidence": 0.8148, "bbox": [450, 182, 540, 255] },
      { "equipment_item": "colete", "compliance": "ABSENT", "confidence": 0.5835 }
    ],
    "uncertain": false
  }
}
```

Regras do contrato de saída:

* uma mensagem por pessoa; quadro sem pessoas não publica nada;
* `captured_at`, `source_id`, `session_id` e `sequence` são os do quadro do I1;
  `frame_index`, `detection_id` e `bbox` são os da pessoa no I1, sem conversão,
  para o S2 casar com o rastro do I2;
* `calibrated` é `true` quando a homografia do I3 para `source_id` foi aceita e
  usada na associação; sem ela o I9 opera em pixels;
* `catalog_version` é o `artifact_version` do PPE_CATALOG em uso ou, com a
  lista local de `config/policy.json`, `local-<policy_id>-<version>`;
* `artifact_version` é a versão do modelo do I9: `artifact_version` da política
  ou, por padrão, `i9-geom-<policy_id>-<version>`;
* `items[].compliance` é `CORRECT`, `INCORRECT` ou `ABSENT`; `items[].bbox`
  é a caixa do EPI no I1 e não aparece em `ABSENT`;
* `uncertain` é `true` quando algum item é incerto ou há oclusão severa;
* `confidence` (0–1) é um score geométrico do quadro atual, não uma
  probabilidade calibrada.

Para diagnóstico, `ComplianceEvent.frame_report()` (e a saída sem `--json`)
mostra o quadro inteiro: evidências, EPIs sem dono e detecções descartadas.
Esse relatório não é publicado.

## Catálogo de EPI (PPE_CATALOG do A5)

A lista de EPIs vem do A5. O I9 recebe o anúncio em `ods.artifact.published`
(`kind: PPE_CATALOG`), baixa o conteúdo pela `uri` e confere o `hash_sha256`
(`src/adapters/catalog_adapters.py`):

* `registry://a5/<artifact_id>/<n>` → `GET {A5_REGISTRY_BASE_URL}/registro/<artifact_id>/<n>`;
  `http(s)://` e `file://` são lidos diretamente;
* o hash é conferido sobre os bytes recebidos ou, se não bater, sobre o JSON
  canônico (chaves ordenadas, sem espaços); hash divergente rejeita o catálogo;
* anúncios de outros tipos ou de outro dono (`I9_CATALOG_OWNER`, padrão `A5`)
  são ignorados; catálogo inválido ou registro fora do ar mantém a lista em uso.

Como cada campo é usado:

| Campo do A5 | Uso no I9 |
|---|---|
| `items[].equipment_item` | classe canônica; sai **sem alteração** em `equipment_item` |
| `items[].class_aliases` | classes do I1 que correspondem ao item (comparação sem caixa) |
| `items[].name` | não usado (exibição é do A5) |
| `required[].items` | a **união** de todas as zonas é avaliada (inclusive `AUSENTE`); itens fora da união só aparecem quando detectados |
| `required[].zone_id` | não usado: decidir a zona da pessoa e o que é exigido nela é do **S2** |

A zona do corpo de cada item (o `body_part` do 6c) é conhecimento anatômico do
I9 e fica em `item_zones` de `config/policy.json`. Item do catálogo sem zona
conhecida não é avaliado e é registrado no log.

```json
"item_zones": {
  "capacete": "HEAD", "oculos": "HEAD", "mascara": "HEAD", "protetor_auricular": "HEAD",
  "colete": "TORSO", "luvas": "HANDS", "bota": "FEET"
}
```

Sem catálogo (antes do primeiro anúncio, nos mocks e na calibração com dataset)
vale a lista local `equipment`:

```json
{ "class": "capacete", "aliases": ["capacetes", "helmet", "hardhat"], "required": true, "zone": "HEAD" }
```

Os blocos `association`, `confidence` e `calibration` são opcionais: todos os
parâmetros têm default no motor e servem apenas para ajuste fino. Eles continuam
valendo quando o catálogo do A5 substitui a lista local.

### Zonas do corpo

A geometria vive no motor (`src/domain/body_zones.py`), em coordenadas
normalizadas da bounding box da pessoa:

```text
u = (cx_epi - x_min_pessoa) / largura_pessoa     0 = esquerda, 1 = direita
v = (cy_epi - y_min_pessoa) / altura_pessoa      0 = base,     1 = topo
```

Como a origem é inferior, a cabeça fica em `v` alto:

| Zona | Região | `u` | `v` | Tolerância |
|---|---|---|---|---|
| `HEAD` | cabeça | 0.28 – 0.72 | 0.72 – 1.10 | 0.18 / 0.18 |
| `TORSO` | tronco | 0.20 – 0.80 | 0.38 – 0.74 | 0.20 / 0.16 |
| `HANDS` | mãos/quadro | 0.02 – 0.98 | 0.10 – 0.55 | 0.15 / 0.18 |
| `FEET` | pés | 0.05 – 0.95 | −0.06 – 0.14 | 0.15 / 0.10 |

`HEAD` passa de `v = 1.0` porque um capacete legitamente ultrapassa o topo da
bounding box da pessoa. `FEET` é uma heurística inicial, sem dados anotados de
botas para calibrar. Uma zona desconhecida é **erro de configuração**: o
carregamento falha e a mensagem lista as zonas disponíveis.

## Regras

1. **Classificação das detecções** — confiança abaixo de
   `min_detection_confidence` (0.25) e classes fora da política vão para
   `ignored_detections`; as demais são separadas em pessoas e EPIs.
2. **Associação (score de 0 a 1)** — combinação ponderada de:
   * contenção/IoU entre a bbox do EPI e a da pessoa (com pequena expansão);
   * proximidade horizontal e faixa vertical em coordenadas normalizadas;
   * distância no plano do ambiente, quando há calibração válida (apenas como
     corte: acima de `ground_radius_m` o par é descartado).
3. **Casamento um-para-um** — pares ordenados por score; o melhor vence, e cada
   pessoa e cada EPI participam de no máximo um casamento. EPIs abaixo de
   `min_association` vão para `unassociated_equipment`.
4. **Posicionamento** — score de zona: 1.00 no centro, 0.70 na borda, decaindo
   linearmente até zero ao longo da tolerância.
5. **Estado** — `CORRETO` se o posicionamento ≥ `correct_threshold` (0.75),
   `INCORRETO` se estiver associado abaixo disso, `AUSENTE` se nenhum candidato
   foi associado. São exatamente três estados, conforme o contrato.
6. **Confiança** —
   * `CORRETO`: `associação × posicionamento`
   * `INCORRETO`: `associação × (1 − posicionamento)`
   * `AUSENTE`: `absence_base`, reduzido quando existe um EPI da mesma classe sem
     dono, e limitado por `absence_max`
   * limitada por `max_confidence` (0.95), pois ainda não há calibração estatística;
   * multiplicada pela `confidence` da detecção do I1 (do EPI; da pessoa no
     caso de `AUSENTE`).
7. **Incerteza** — o item sai `uncertain: true` quando a confiança final fica
   abaixo de `uncertain_below` (0.50). Quando outra pessoa cobre pelo menos
   `occlusion_overlap` (40%) da caixa da pessoa, todos os itens dela saem
   incertos com `uncertain_reasons: ["severe_occlusion"]`.

Quando o EPI está integralmente contido na pessoa, a associação satura em 100% e
a confiança passa a ser determinada essencialmente pelo posicionamento — o que é
o comportamento esperado para um enquadramento limpo.

## Estendendo

| Mudança | Onde | Exige deploy? |
|---|---|---|
| Novo EPI / alias / obrigatoriedade | cadastro do A5 (`PPE_CATALOG`) | não |
| Zona do corpo de um EPI novo | `config/policy.json` (`item_zones`) | não |
| Lista local (sem A5) | `config/policy.json` (`equipment`) | não |
| Ajuste fino de limiar | `config/policy.json` (`association` / `confidence`) | não |
| **Nova zona do corpo** | `src/domain/body_zones.py` + teste | **sim** |

Exemplo: o A5 cadastra `cinto` → basta acrescentar `"cinto": "TORSO"` em
`item_zones`; até isso acontecer, o item é ignorado com aviso no log.

## Limitações conhecidas

* Bounding boxes não distinguem EPI **usado** de EPI **segurado** próximo ao corpo.
* Uma zona é um retângulo único: classes com dois pontos de uso (luvas nas duas
  mãos, protetor auricular nas duas orelhas) ficam representadas por uma região
  única e precisam de refinamento.
* `AUSENTE` não distingue oclusão de ausência real — por isso a confiança é
  limitada e o S2 deve consolidar o estado ao longo dos quadros.
* Distinguir uso real de coincidência geométrica pode exigir keypoints, pose,
  segmentação ou um modelo, que pode ser plugado no lugar de
  `RelationInferenceModule` sem alterar o contrato de saída.
