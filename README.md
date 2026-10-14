# S3 — Alertas e Notificações

Componente S3 da arquitetura 6c da ODS 2026/2, do squad **VER-3 (EPI)**.

O S3 leva o evento qualificado à pessoa certa, pelo canal certo, e registra o que aconteceu depois: quem reconheceu, quem silenciou e quem encerrou o alerta. Ele não tem regra de EPI no código. O que cada tipo de evento gera vem do artefato **ROUTING** da aplicação, por isso o mesmo S3 atende A5 (EPI), A3 e A7.

Os contratos seguem a **Especificação de interfaces 1.0 (arquitetura 6c)**. O transporte segue o **Guia de Uso do Kafka** da TRA-1.

## Onde o S3 está

```
I1 → I9 → S2 (VER-6) ──ods.s2.event──► S3 ──ods.s3.alert──► A3, A5, A7 (A1, A2 opcionais)
                                        ▲
        A3/A5/A7 ── artefato ROUTING ───┤
        aplicações ── comandos ─────────┤──► reply
        aplicações ── consulta ─────────┘──► reply
```

| Direção | Schema | Perfil | Quem |
|---|---|---|---|
| Entrada | `ods.s2.event` | EV-SERVIÇO | S2 publica |
| Entrada | artefato `ROUTING` | — | A3, A5 e A7 são donos |
| Saída | `ods.s3.alert` | EV-SERVIÇO | Publicado na criação e a cada mudança de estado |
| Comando | `ods.s3.alert.command` → `.reply` | CMD / RPL | A1, A2, A3, A5 e A7 criam alertas de negócio |
| Comando | `ods.s3.alert_action.command` → `.reply` | CMD / RPL | ACKNOWLEDGE, MUTE e CLOSE |
| Consulta | `ods.s3.alerts.query` → `ods.s3.alerts.reply` | CMD / RPL | Histórico com filtros e paginação |

Há exemplos completos de cada mensagem em [`jsons/`](jsons/).

## Ciclo de vida do alerta

| Estado de destino | Pode vir de | Comando |
|---|---|---|
| `CREATED` | — (criação) | evento roteado ou `alert.command` |
| `ACKNOWLEDGED` | `CREATED` | `ACKNOWLEDGE` |
| `MUTED` | `CREATED`, `ACKNOWLEDGED` | `MUTE` (exige `mute_until`) |
| `CLOSED` | `CREATED`, `ACKNOWLEDGED`, `MUTED` | `CLOSE` (estado final) |

- A especificação define os estados, mas **não as transições**. Esta tabela é decisão do VER-3 e ainda precisa ser revisada (ver pendências).
- Transição fora da tabela → reply `ERROR` com `INVALID_TRANSITION`, sem alterar nada.
- Cada ação gera um registro de histórico imutável, com autor (`actor`), motivo (`reason`) e horário com fuso.
- O alerta publicado traz `acknowledged_by/at`, `muted_until` e `closed_by/at`.

## Regras de mensagens

- **Envelope comum de 13 campos.** Horários em ISO 8601 UTC com milissegundos (`2026-09-23T14:29:59.870Z`). Aceita qualquer versão `1.x`.
- **Mensagem inválida** (JSON quebrado, envelope ou payload fora do contrato) é **descartada e registrada em log**, nunca processada "na tentativa".
- **Duplicatas:**
  - mensagem com `message_id` já processado é descartada;
  - o mesmo `event_id` gera um alerta só; as fases `UPDATED` e `ENDED` não criam outro;
  - comando repetido (mesmo `message_id`) recebe **a mesma reply**, sem novo efeito.
- **Roteamento:**
  - tipo de evento sem rota não gera alerta e não é erro;
  - evento `UNCERTAIN` só vira alerta se a rota tiver `min_status: UNCERTAIN`;
  - `title` e `message` da rota são modelos com `{campo}`, preenchidos com os campos do evento (`{equipment_item}`, `{zone_id}`, `{duration_s}`…).
- **Destinatários:** `user:<id>`, `group:<id>` ou `role:<id>`.
- **Canais:** `SOUND`, `SCREEN`, `PUSH`.
- **Severidades:** `HIGH`, `MEDIUM`, `LOW`.

## Estrutura

| Arquivo | Responsabilidade |
|---|---|
| `src/s3/envelope.py` | Envelope comum: montar, validar, horários, `sequence` |
| `src/s3/errors.py` | `ErroS3` com o código que vai em `error.code` |
| `src/s3/contracts.py` | `EventoQualificado` e a leitura de `ods.s2.event` |
| `src/s3/routing.py` | Artefato ROUTING, rotas e preenchimento de `title`/`message` |
| `src/s3/alert.py` | Modelo `Alerta` e validação de destinatários, canais e severidade |
| `src/s3/history.py` | `RegistroHistorico` imutável |
| `src/s3/repository.py` | Alertas, histórico e `message_id` processados (em memória) |
| `src/s3/service.py` | Criação, deduplicação, transições e consulta |
| `src/s3/output.py` | Monta `ods.s3.alert` |
| `src/s3/ingestion.py` | Recebe `ods.s2.event` |
| `src/s3/commands.py` | Atende os comandos e a consulta e monta as replies |
| `src/s3/subscription.py` / `publication.py` | Interfaces com o barramento e descarte com log |
| `src/s3/kafka_adapter.py` | Adaptador Kafka (`confluent-kafka`) |
| `src/s3/__main__.py` | Executa o S3 ligado ao Kafka |
| `demo_s3.py` | Demonstração com assinante e publicador falsos |
| `tests/s3/` | Testes (`fabricas.py` monta mensagens válidas) |

## Instalar e testar (PowerShell)

Requer Python 3.10 ou mais novo. O núcleo usa só a biblioteca padrão.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt     # pytest e confluent-kafka

$env:PYTHONPATH = "src"
python -m pytest tests/s3 -q            # ou: python -m unittest discover -s tests/s3 -p "test_*.py"
python demo_s3.py
```

Os testes **não acessam o broker real**: usam assinante, publicador e cliente Kafka falsos.

## Executar com o Kafka

```powershell
$env:PYTHONPATH = "src"
$env:S3_KAFKA_BOOTSTRAP = "<host:porta do broker>"   # ver Guia do Kafka da TRA-1
$env:S3_KAFKA_GROUP_ID = "S3-alertas"                # opcional; este é o padrão
python -m s3 --routing jsons/routing_a5.json --versao-routing routing-a5-1 --tempo-limite 60
```

- O endereço do broker **não fica no código**. O broker de testes está na nuvem e vai mudar para um local.
- Para cada mensagem:
  - o commit do offset só acontece depois do processamento;
  - se o processamento falhar, a mensagem volta na próxima leitura.
- O broker de testes é **pago e compartilhado** pelos 15 squads (Guia do Kafka, 4.5). Por isso `python -m s3` exige `--tempo-limite` ou `--max-mensagens`. Não deixe o processo rodando sem supervisão.
- Por padrão, os tópicos têm o mesmo nome do schema. `PublicadorKafka(topicos={...})` permite usar outra nomenclatura sem mudar o resto do código.
- **Ainda não foi testado contra o broker real.**

## Limitações conhecidas

- **Persistência em memória.** Alertas, histórico e `message_id` processados se perdem quando o processo reinicia. A escolha do banco é decisão da squad: cada build tem o seu, e o P3 opera o armazenamento.
- **Falha ao publicar.** Se o barramento falhar ao publicar `ods.s3.alert`, o alerta já ficou salvo e a mensagem se perde. A solução (fila de saída no banco) depende da persistência.
- **`clip_id`.** Alertas roteados não recebem o `clip_id`, mesmo com `capture: true` (ver pendência 4).
- **`MUTE`.** Quando o prazo `mute_until` vence, o alerta continua `MUTED`.
- **Concorrência.** O serviço supõe um consumidor por processo.

## Pendências com outras equipes

Itens da revisão da especificação (seção 10, item 17), em que o VER-3 é revisor:

| # | Pendência | Com quem |
|---|---|---|
| 1 | Nome dos tópicos: a especificação usa `ods.s3.alert`; o Guia do Kafka sugere `ods.alerta.emitido` | TRA-1 |
| 2 | Campos de horário do envelope: o guia usa `occurred_at`; a especificação usa `published_at`/`captured_at` | TRA-1 |
| 3 | Tópico das replies e como elas chegam a quem pediu | TRA-1 |
| 4 | Como o S3 obtém o `clip_id` do S4, se a lista de consumo do S3 é fechada em S2 | TRA-1, MOD-2 |
| 5 | `session_id` e `sequence` em alertas criados por comando, que não têm sessão de origem | TRA-1, TRA-2 |
| 6 | O que fazer nas fases `UPDATED` (atualizar a mensagem?) e `ENDED` (encerrar o alerta?) | VER-6, A5 |
| 7 | Transições permitidas e o que acontece quando `mute_until` vence | A5, B6 |
| 8 | Autorização: quem pode mandar ACKNOWLEDGE, MUTE e CLOSE | A5, TRA-1 |
| 9 | Códigos de erro que não estão na especificação: `INVALID_PAYLOAD` e `INVALID_MESSAGE` | TRA-1 |

O estado completo do componente está em [README_S3_ODS.md](README_S3_ODS.md).
