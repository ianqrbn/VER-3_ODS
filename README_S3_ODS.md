# S3 — Alertas e Notificações (Squad VER-3)

## Resumo

O S3 já tem uma base funcional para processar eventos qualificados em memória: valida eventos, resolve uma configuração de roteamento, cria alertas, evita duplicatas dentro do repositório atual, registra histórico e oferece operações de reconhecimento (ACK) e silenciamento (MUTE).

**Ainda não é uma integração operacional completa.** Não há cliente de barramento real, publicador de saída, persistência durável, despacho efetivo de notificações nem integração ponta a ponta comprovada.

## Arquitetura implementada

```text
AssinanteEventos (interface abstrata; sem broker concreto)
    ↓ callback
ConectorEventos
    ↓
IngestorEventos (JSON → EventoQualificado)
    ↓
AlertService.processar_evento_roteado()
    ↓
RoteadorAlertas (tipo → severidade/destinatários/canais)
    ↓
AlertService.processar_evento()
    ↓
AlertRepository em memória (alerta + histórico)
```

Na arquitetura de referência da squad, o S2 é o produtor esperado dos eventos qualificados para o S3. Os comandos ACK/MUTE são métodos Python no serviço; não há endpoint nem consumidor de mensagens de comando implementado.

## Estrutura do projeto

- `demo_s3.py`: demonstração manual usando assinante simulado.
- `jsons/entrada.json`: exemplo de envelope de entrada.
- `jsons/saida.json`: exemplo de envelope de alerta de saída.
- `src/s3/contracts.py`: `EventoQualificado` e validação básica.
- `src/s3/alert.py`: modelo `Alerta`.
- `src/s3/history.py`: `RegistroHistorico`, imutável como objeto.
- `src/s3/repository.py`: armazenamento em memória e busca por alerta/evento.
- `src/s3/routing.py`: regras de severidade, destinatários e canais.
- `src/s3/service.py`: criação, deduplicação, ACK e MUTE.
- `src/s3/ingestion.py`: decodificação JSON e encaminhamento.
- `src/s3/subscription.py`: protocolo de assinatura e callback.
- `tests/s3/`: testes unitários e teste com assinante falso.

## O que funciona

### Ingestão e validação
- Rejeita JSON inválido ou que não seja objeto.
- Valida campos obrigatórios do evento e confiança entre 0 e 1.
- Campos opcionais: `pessoa_id`, `zona_id`, `evidencia_ref`.
- O timestamp é verificado apenas como texto não vazio; não há validação de ISO-8601/fuso horário.

### Roteamento
- O tipo do evento é associado a uma configuração fixa de severidade, destinatários e canais.
- Canais aceitos: `SOM`, `TELA`, `PUSH`.
- Evento sem regra de roteamento é rejeitado.
- A severidade é configurada pela regra de roteamento; o código não a calcula dinamicamente a partir de confiança, duração ou política de negócio.

### Alertas e histórico
- Alerta com ID, evento de origem, severidade, destinatários, canais, evidência, estado e horário UTC.
- Estados exercitados no serviço: `CRIADO`, `RECONHECIDO`, `SILENCIADO`.
- O histórico registra `CRIADO` automaticamente e autor/horário para reconhecimento e silenciamento.
- `ENCERRADO` existe entre as ações aceitas pelo modelo de histórico, mas não há método para encerrar alerta.
- O registro histórico é imutável como dataclass, mas o repositório é volátil e os dados se perdem ao encerrar o processo.
- Deduplicação é limitada à instância atual do repositório em memória.

### Integração e envelopes
- `ConectorEventos` registra o ingestor como callback de um assinante que implemente o protocolo.
- Os testes usam um assinante falso: validam a integração interna, não o Pub/Sub/B3 real.
- `jsons/entrada.json` usa um envelope com `payload` aninhado. Porém, `IngestorEventos` espera os campos de `EventoQualificado` diretamente na raiz; o exemplo não é aceito sem adaptação.
- `jsons/saida.json` é apenas um exemplo documental: não existe publicador de saída no código.

## Executar no PowerShell

Requisito recomendado: Python 3.10+ (a revisão foi executada com Python 3.12).

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m unittest discover -s tests/s3 -p "test_*.py" -v
$env:PYTHONPATH = "src"
python demo_s3.py
```

## Testes desta revisão

**PASSOU — Ran 56 tests in 0.004s**

Os testes aprovados cobrem comportamento interno e simulação. Não comprovam broker real, armazenamento durável, envio real de notificações nem integração ponta a ponta.

## Pendências recomendadas

### Prioridade 1 — contratos e integração
1. Acordar com B3/TRA-1 transporte, tópico, envelope, versão de schema, confirmação de consumo, retry, ordenação e tratamento de mensagens inválidas.
2. Alinhar `IngestorEventos` ao envelope oficial: extrair `payload` ou atualizar os exemplos.
3. Implementar adaptador de broker concreto e testes de integração.
4. Implementar publicação dos alertas e definir consumidores/contratos de saída.
5. Definir como comandos ACK/MUTE chegam ao S3 e como a autorização é verificada.

### Prioridade 2 — confiabilidade e requisitos funcionais
6. Persistir alertas e histórico em banco de dados.
7. Implementar encerramento e regras formais de transição de estado.
8. Garantir idempotência durável para mensagens e comandos, inclusive após reinício/concorrência.
9. Implementar retry, dead-letter, backpressure, logs e métricas.
10. Integrar os canais `SOM`, `TELA` e `PUSH` ou delegar formalmente o despacho.
11. Criar testes ponta a ponta S2 → S3 → consumidores.
12. Validar formato e fuso horário do timestamp.

### Prioridade 3 — qualidade
13. Validar explicitamente severidades, estados e valores dos campos.
14. Decidir se ACK repetido deve ser rejeitado: atualmente o serviço não bloqueia explicitamente novo reconhecimento quando o alerta já está `RECONHECIDO`.
15. Definir política de concorrência, pois o repositório retorna objetos `Alerta` mutáveis.
16. Remover `__pycache__` e `.pyc` do versionamento.
17. Substituir o README original, que contém apenas o título, por documentação completa.

## Critérios de aceite sugeridos

- Uma mensagem no contrato oficial gera exatamente um alerta.
- Mensagens repetidas não duplicam alertas nem histórico.
- ACK/MUTE só são aceitos de origem autorizada e registram autor/horário.
- Alertas e histórico sobrevivem ao reinício.
- Encerramento segue transições documentadas.
- Saída publicada no contrato acordado é consumida por componente real.
- Testes cobrem retry, sobrecarga, recuperação e integração ponta a ponta.

## Limites da análise

A análise foi feita sobre o ZIP enviado e os testes executados nesta revisão. Não confirma contratos externos, infraestrutura ou o estado dos outros componentes. Capacidades não demonstradas no código foram registradas como pendentes.
