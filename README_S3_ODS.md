# S3 — Alertas e Notificações (Squad VER-3): estado do componente

*Atualizado em 14/10/2026, depois da migração para a Especificação de interfaces 1.0.*

## Resumo

O S3 segue os contratos oficiais da **Especificação de interfaces 1.0 (arquitetura 6c)**:
- recebe `ods.s2.event`;
- aplica o artefato ROUTING;
- publica `ods.s3.alert` na criação e a cada mudança de estado;
- atende os comandos `ods.s3.alert.command` e `ods.s3.alert_action.command` e a consulta `ods.s3.alerts.query`, com reply e idempotência pelo `message_id`.

Também existe um adaptador Kafka que segue o Guia de Uso do Kafka da TRA-1.

**Ainda não é uma integração operacional comprovada.** O adaptador Kafka nunca foi executado contra o broker real, a persistência é em memória e há decisões de contrato pendentes com outras equipes.

## O que mudou nesta versão

| Antes (contrato provisório) | Agora (Especificação 1.0) |
|---|---|
| Entrada com campos em português (`evento_id`, `tipo`, `timestamp`), com ou sem envelope | Só `ods.s2.event` com o envelope comum. O formato antigo é rejeitado |
| Severidade `ALTA`, canais `SOM/TELA/PUSH`, destinatários livres | `HIGH/MEDIUM/LOW`, `SOUND/SCREEN/PUSH`, `user:`/`group:`/`role:` |
| Roteamento montado no código | Artefato ROUTING carregado de arquivo, com `min_status`, `title`/`message` e `capture` |
| Estados `CRIADO`, `RECONHECIDO`, `SILENCIADO`, `ENCERRADO` | `CREATED`, `ACKNOWLEDGED`, `MUTED` (com `mute_until`), `CLOSED` |
| Saída sem autor e com horários em segundos | `acknowledged_by/at`, `muted_until`, `closed_by/at`; horários com milissegundos |
| Comandos só como funções Python | Mensagens com reply `OK`/`ERROR` e códigos (`ALERT_NOT_FOUND`, `INVALID_TRANSITION`, `INVALID_RECIPIENT`, `INVALID_CHANNEL`) |
| Sem consulta | `ods.s3.alerts.query` com filtros e paginação |
| Sem transporte | `kafka_adapter.py` e `python -m s3` |

Os nomes internos (`Alerta`, `EventoQualificado`, `evento_id`…) continuam em português. A tradução para os nomes do contrato fica só na borda: `contracts.py`, `output.py` e `commands.py`.

## Bugs corrigidos

1. **Destinatário sem vírgula virava lista de letras.** `("supervisor-01")` não é uma tupla, é texto, e virava `['s','u','p',…]`. Agora o campo precisa ser uma lista ou tupla, e cada destinatário precisa ter um prefixo válido.
2. **O estado do alerta podia mudar sem passar pelo histórico.** O repositório agora devolve cópias. O estado só muda por `atualizar()`, que grava estado e histórico juntos e não altera nada se algo for inválido.
3. **Validações fracas:**
   - `timestamp` aceitava qualquer texto; agora todo horário precisa ser ISO 8601 com fuso;
   - autor feito só de espaços era aceito; agora é rejeitado;
   - severidade, estado e canal não eram conferidos; agora são.
4. **`ENDED` criava alerta.** Um `ENDED` de evento sem alerta existente criava um alerta novo para uma violação já terminada. Agora não cria, e o caso é registrado em log.
5. **`actor` sem formato.** O `actor` dos comandos aceitava qualquer texto. Agora precisa ser `user:<id>`.
6. **Teste duplicado.** `test_reconhecer_alerta` tinha duas definições e uma apagava a outra (corrigido na revisão anterior).

## Testes

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/s3 -q
```

**Resultado:** 176 testes e 63 subtestes passando (pytest e unittest).

O que os testes cobrem:
- envelope e horários;
- leitura de `ods.s2.event`, incluindo o arquivo real `jsons/entrada.json`;
- roteamento, incluindo o artefato `jsons/routing_a5.json`;
- ciclo de vida e histórico;
- deduplicação por `message_id` e por `event_id`;
- saída igual a `jsons/saida.json`;
- os três comandos, incluindo os arquivos de exemplo;
- descarte de mensagem inválida com log;
- adaptador Kafka com cliente falso.

O que os testes **não** cobrem: broker real, persistência durável, envio real por som, tela e push, e integração ponta a ponta com o S2 e as aplicações.

## Pendências

### Internas (não dependem de outras equipes)
1. **Persistência em banco.** Sugestão: SQLite. A squad ainda não decidiu. O mesmo banco também resolveria:
   - a perda de mensagem quando a publicação falha (fila de saída);
   - a deduplicação, que hoje se perde quando o processo reinicia.
2. **Teste manual curto contra o broker de testes,** combinado com a TRA-1.
3. **Organização do repositório.** Documentos de outras equipes estão versionados junto com o código (PDFs, SVG da arquitetura). O ideal é movê-los para `docs/` ou removê-los do git.
4. **`Analise_Projeto_S3_ODS.pdf` está desatualizado** em relação a este documento.

### Com outras equipes
As 11 perguntas estão na seção "Pendências com outras equipes" do [README.md](README.md). As mais urgentes:
- o nome dos tópicos (TRA-1);
- como o S3 obtém o `clip_id` (TRA-1 e MOD-2);
- o comportamento nas fases `UPDATED` e `ENDED` (VER-6 e A5).

## Critérios de aceite

- [x] Uma mensagem `ods.s2.event` válida gera exatamente um alerta.
- [x] Mensagens e eventos repetidos não duplicam alertas nem histórico.
- [x] Comandos registram autor, motivo e horário, e respondem com o contrato oficial.
- [x] O encerramento segue transições documentadas.
- [ ] ACK, MUTE e CLOSE só são aceitos de origem autorizada (pendência 8).
- [ ] Alertas e histórico sobrevivem ao reinício (persistência).
- [ ] A saída publicada é consumida por um componente real, através do broker real.
- [ ] Testes de integração ponta a ponta S2 → S3 → A5.
