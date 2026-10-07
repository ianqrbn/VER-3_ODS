# I9 · Verificador de EPI por pessoa

Verificação **geométrica** (sem modelo de visão computacional) do uso de EPI por
pessoa, a partir das bounding boxes e do rastreio recebidos do **I2**.

Para cada pessoa e para cada classe de EPI definida na política da aplicação, o
componente emite um estado relacional — `CORRETO`, `INCORRETO` ou `AUSENTE` —
com uma porcentagem de confiança e as demais informações recebidas do frame.

O I9 é um verificador **especializado em pessoas**: a anatomia (cabeça, tronco,
mãos) e sua geometria são conhecimento do motor. A aplicação configura apenas
*quais* EPIs existem, *quais* são obrigatórios e *em qual zona* cada um deve ser
usado.

## Execução

```bash
cd I9
python3 main.py            # resumo legível dos 3 quadros simulados
python3 -m unittest discover -s tests -t .
```

Sem dependências externas: apenas a biblioteca padrão do Python 3.10+.

## Fluxo

```text
I2  ods.inferencia.rastreio ──┐
                              ├─► I9Pipeline ─► PairingModule ─► RelationInferenceModule ─► ods.inferencia.relacional
I3  ods.inferencia.calibracao ┘                     (associação)      (estado + confiança)
```

* `I9Pipeline` (`src/core/pipeline.py`) orquestra um quadro por vez, sem estado
  acumulado: as **regras temporais são responsabilidade do I2**.
* `PairingModule` (`src/core/pairing.py`) associa EPIs a pessoas de forma
  **um-para-um** (EPIs são individuais).
* `RelationInferenceModule` (`src/core/inference.py`) decide o estado relacional.
* `CalibrationStore` (`src/core/calibration.py`) valida e guarda a homografia do I3.
* `body_zones.py` (`src/domain/body_zones.py`) guarda a geometria do corpo humano.
* A política fica **fora do código**, em `config/policy.json`.

## Contratos

### Entrada — rastreio (I2)

Origem da imagem no canto **inferior esquerdo** e `x_max` / `y_max` **exclusivos**,
no mesmo espaço de pixels de `u_px` / `v_px`.

```json
{
  "message_type": "event",
  "schema": "ods.inferencia.rastreio",
  "schema_version": "1.0",
  "producer": "I2",
  "published_at": "2026-09-23T14:05:12.402Z",
  "payload": {
    "camera_id": "CAM-01",
    "session_id": "sess-2026-09-23-a",
    "captured_at": "2026-09-23T14:05:12.400Z",
    "frame": 12345,
    "frame_width": 1920,
    "frame_height": 1080,
    "tracks": [
      {
        "track_id": 42,
        "class": "pessoa",
        "state": "confirmed",
        "u_px": 540.0,
        "v_px": 640.0,
        "predicted": false,
        "bbox": { "x_min": 412.0, "y_min": 268.0, "x_max": 668.0, "y_max": 1012.0 }
      }
    ]
  }
}
```

`state` aceita `confirmed`, `predicted` e `lost`. `frame_width`, `frame_height` e
`frame` são opcionais. Campos adicionais de cada track são preservados e
repassados sem alteração na saída.

### Entrada — calibração (I3)

```json
{
  "message_type": "event",
  "schema": "ods.inferencia.calibracao",
  "schema_version": "1.0",
  "producer": "I3",
  "published_at": "2026-09-23T13:58:00.000Z",
  "payload": {
    "camera_id": "CAM-01",
    "calibration_version": "cam-01-v3",
    "valid_from": "2026-09-23T13:58:00.000Z",
    "homography": [[0.004, -0.0002, 0.85], [0.0001, -0.0042, 1.15], [-0.0000009, 0.0000021, 1.0]],
    "reference_frame": { "space_id": "obra-civil", "origin": "0,0", "axes": "x_direita,y_frente", "unit": "m" },
    "reprojection_rms_cm": 1.8,
    "holdout_points": 6
  }
}
```

A matriz é recebida, validada e armazenada por câmera. Ela é usada como **corte
de alcance** e como informação de auditoria, não como critério de posição: como
a homografia projeta o chão, um capacete na cabeça cai longe do ponto do tronco.

### Saída — evento relacional (I9)

```json
{
  "message_type": "event",
  "schema": "ods.inferencia.relacional",
  "schema_version": "1.0",
  "producer": "I9",
  "published_at": "2026-09-23T14:05:12.450Z",
  "payload": {
    "camera_id": "CAM-01",
    "session_id": "sess-2026-09-23-a",
    "frame": 12345,
    "captured_at": "2026-09-23T14:05:12.400Z",
    "frame_width": 1920,
    "frame_height": 1080,
    "calibration_version": "cam-01-v3",
    "calibration_status": "valid",
    "policy_id": "default",
    "policy_version": "1.0",
    "relations": [
      {
        "person": { "track_id": 42, "class": "pessoa", "...": "track original do I2" },
        "equipment": [
          {
            "class": "CAPACETES",
            "required": true,
            "relational_state": "CORRETO",
            "confidence_pct": 95.0,
            "detection": { "track_id": 101, "...": "track original do I2" },
            "evidence": {
              "association_score_pct": 100.0,
              "placement_score_pct": 97.04,
              "person_normalized_center": { "u": 0.5, "v": 0.9288 },
              "expected_zone": "HEAD",
              "ground_distance_m": 1.338
            }
          },
          {
            "class": "LUVAS",
            "required": true,
            "relational_state": "AUSENTE",
            "confidence_pct": 62.0,
            "detection": null,
            "evidence": { "reason": "no_candidate_in_person_region", "zone": "HANDS" }
          }
        ]
      }
    ],
    "unassociated_equipment": [
      { "class": "CAPACETES", "track": { "track_id": 301 }, "reason": "below_association_threshold", "best_association_score_pct": 0.01 }
    ],
    "ignored_tracks": [
      { "track": { "track_id": 202 }, "reason": "track_state_lost" }
    ]
  }
}
```

Regras do contrato de saída:

* um evento por quadro, mesmo sem pessoas (`relations: []`);
* `relational_state` evita colisão com o `state` do rastreador;
* `AUSENTE` sempre traz `detection: null`;
* **todo track de entrada aparece exatamente uma vez**: em `relations` (pessoa ou
  `detection`), em `unassociated_equipment` ou em `ignored_tracks`;
* `confidence_pct` é um score geométrico do quadro atual, não uma probabilidade
  calibrada — deve ser ajustado com dados anotados antes de virar garantia.

## Política de EPI (`config/policy.json`)

As classes variam por aplicação (por exemplo, o capacete pode não ser exigido em
determinados contextos). A configuração é enxuta de propósito: **qual** EPI, **em
qual zona** e se é **obrigatório**.

```json
{
  "class": "CAPACETES",
  "aliases": ["capacete", "capacetes", "CAPACETE", "helmet"],
  "required": true,
  "zone": "HEAD"
}
```

Os blocos `association`, `confidence` e `calibration` são opcionais: todos os
parâmetros têm default no motor e servem apenas para ajuste fino.

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

`HEAD` passa de `v = 1.0` porque um capacete legitamente ultrapassa o topo da
bounding box da pessoa. Uma zona desconhecida é **erro de configuração**: o
carregamento falha e a mensagem lista as zonas disponíveis.

## Regras

1. **Classificação dos tracks** — `lost` e classes fora da política vão para
   `ignored_tracks`; os demais são separados em pessoas e EPIs.
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
   * multiplicada por `predicted_factor` (0.70) para tracks `predicted` e
     `unknown_state_factor` (0.50) para estado desconhecido;
   * limitada por `max_confidence` (0.95), pois ainda não há calibração estatística.

Quando o EPI está integralmente contido na pessoa, a associação satura em 100% e
a confiança passa a ser determinada essencialmente pelo posicionamento — o que é
o comportamento esperado para um enquadramento limpo.

## Estendendo

| Mudança | Onde | Exige deploy? |
|---|---|---|
| Nova classe de EPI | `config/policy.json` | não |
| Tornar classe opcional | `config/policy.json` (`required: false`) | não |
| Novo alias de detecção | `config/policy.json` (`aliases`) | não |
| Ajuste fino de limiar | `config/policy.json` (`association` / `confidence`) | não |
| **Nova zona do corpo** | `src/domain/body_zones.py` + teste | **sim** |

Exemplo de classe nova sem tocar em código:

```json
{ "class": "PROTETORES_AURICULARES", "aliases": ["protetor_auricular"], "required": true, "zone": "HEAD" }
```

## Limitações conhecidas

* Bounding boxes não distinguem EPI **usado** de EPI **segurado** próximo ao corpo.
* Uma zona é um retângulo único: classes com dois pontos de uso (luvas nas duas
  mãos, protetor auricular nas duas orelhas) ficam representadas por uma região
  única e precisam de refinamento.
* `AUSENTE` não distingue oclusão de ausência real — por isso a confiança é
  limitada e o I2 deve consolidar o estado pela contagem de quadros.
* Distinguir uso real de coincidência geométrica pode exigir keypoints, pose,
  segmentação ou um modelo, que pode ser plugado no lugar de
  `RelationInferenceModule` sem alterar o contrato de saída.
