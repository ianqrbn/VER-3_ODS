"""
Demonstração ao vivo do componente S3 (Alertas e Notificações).

Simula o S2 publicando um evento qualificado através de um assinante
falso (substituto do broker real do B2, que ainda não existe), e mostra
o alerta passando pelo roteamento, criação, reconhecimento e silenciamento.

Para rodar:
    PowerShell:  $env:PYTHONPATH = "src"; python demo_s3.py
    Git Bash:    PYTHONPATH=src python demo_s3.py
"""

from s3.ingestion import IngestorEventos
from s3.repository import AlertRepository
from s3.routing import ConfiguracaoRoteamento, RoteadorAlertas
from s3.service import AlertService
from s3.subscription import ConectorEventos


class AssinanteDemo:
    """Substituto simples do assinante real do B2, só para esta demonstração."""

    def __init__(self):
        self.callback = None

    def assinar(self, callback):
        self.callback = callback

    def publicar(self, mensagem):
        return self.callback(mensagem)


def titulo(texto):
    print()
    print("=" * 60)
    print(texto)
    print("=" * 60)


def passo(texto):
    print(f"\n>> {texto}")


def main():
    titulo("1. Montagem do S3")

    repo = AlertRepository()

    roteador = RoteadorAlertas({
        "VIOLACAO_EPI": ConfiguracaoRoteamento(
            severidade="ALTA",
            destinatarios=("supervisor-01",),
            canais=("SOM", "TELA"),
        )
    })

    service = AlertService(repository=repo, roteador=roteador)
    ingestor = IngestorEventos(service)
    print("AlertRepository, RoteadorAlertas, AlertService e IngestorEventos prontos.")

    titulo("2. Ligação com o barramento")

    assinante = AssinanteDemo()
    ConectorEventos(assinante, ingestor).conectar()
    print("ConectorEventos conectado a um assinante de demonstração.")

    titulo("3. S2 publica um evento qualificado (simulação de entrada)")

    mensagem = (
        '{"evento_id": "evt-demo-001", "tipo": "VIOLACAO_EPI", '
        '"origem": "S2", "timestamp": "2026-10-08T10:00:00Z", '
        '"confianca": 0.93, "pessoa_id": "pessoa-12", '
        '"zona_id": "producao", "evidencia_ref": "evidencia-demo-001"}'
    )
    print(f"Mensagem recebida:\n{mensagem}")

    alerta = assinante.publicar(mensagem)

    passo("Alerta criado:")
    print(f"   evento_id     = {alerta.evento_id}")
    print(f"   severidade    = {alerta.severidade}")
    print(f"   destinatarios = {alerta.destinatarios}")
    print(f"   canais        = {alerta.canais}")
    print(f"   estado        = {alerta.estado}")

    titulo("4. Supervisor reconhece o alerta")

    alerta = service.reconhecer_alerta(alerta.alerta_id, autor_id="supervisor-01")
    print(f"Novo estado: {alerta.estado}")

    titulo("5. Supervisor silencia o alerta")

    alerta = service.silenciar_alerta(alerta.alerta_id, autor_id="supervisor-01")
    print(f"Novo estado: {alerta.estado}")

    titulo("6. Histórico de auditoria do alerta")

    for registro in repo.buscar_historico(alerta.alerta_id):
        print(f"   {registro.acao:<12} autor={registro.autor_id!s:<15} em={registro.registrado_em}")

    titulo("7. Validação rejeitando um evento inválido")

    mensagem_invalida = (
        '{"evento_id": "evt-demo-002", "tipo": "VIOLACAO_EPI", '
        '"origem": "S2", "timestamp": "2026-10-08T10:05:00Z", '
        '"confianca": 1.5, "pessoa_id": "pessoa-12", '
        '"zona_id": "producao", "evidencia_ref": "evidencia-demo-002"}'
    )
    try:
        assinante.publicar(mensagem_invalida)
    except ValueError as erro:
        print(f"Rejeitado corretamente: {erro}")

    titulo("8. Idempotência: o mesmo evento não cria dois alertas")

    primeiro = assinante.publicar(mensagem)
    segundo = assinante.publicar(mensagem)
    print(f"Mesmo alerta_id? {primeiro.alerta_id == segundo.alerta_id}")

    titulo("Fim da demonstração")


if __name__ == "__main__":
    main()
