#!/bin/bash
# Sobe o I9 (Kafka + serviço) numa VM do Compute Engine com Docker Compose.
#
#   cd I9
#   gcloud auth login && gcloud config set project SEU_PROJETO
#   ./deploy/gce/deploy.sh
#
# A VM é criada com hora de término (TERMINATION_TIME): nesse momento o próprio
# Compute Engine a exclui junto com o disco, mesmo que ninguém rode o teardown.
#
# Variáveis (todas opcionais):
#   VM_NAME           ods-i9
#   ZONE              southamerica-east1-a
#   MACHINE_TYPE      e2-medium
#   TERMINATION_TIME  2026-11-07T00:00:00-03:00 (fim da sexta-feira 06/11, horário de Brasília)
#   ALLOWED_CIDR      faixa de IPs liberada na porta 9092 (ex.: 200.10.20.30/32).
#                     Vazio: o Kafka fica acessível só dentro da VM.
set -euo pipefail

VM_NAME="${VM_NAME:-ods-i9}"
ZONE="${ZONE:-southamerica-east1-a}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-medium}"
TERMINATION_TIME="${TERMINATION_TIME:-2026-11-07T00:00:00-03:00}"
ALLOWED_CIDR="${ALLOWED_CIDR:-}"
FIREWALL_RULE="${VM_NAME}-kafka"

HERE="$(cd "$(dirname "$0")" && pwd)"
I9_DIR="$(cd "$HERE/../.." && pwd)"

ssh_vm() {
  gcloud compute ssh "$VM_NAME" --zone "$ZONE" --quiet --command "$1"
}

hoje="$(TZ=America/Sao_Paulo date +%F)"
if [[ "$hoje" != "2026-11-06" ]]; then
  echo "Hoje é $hoje, não 06/11. A VM roda (e consome créditos) até $TERMINATION_TIME."
  read -r -p "Criar mesmo assim? [s/N] " resposta
  [[ "$resposta" == "s" || "$resposta" == "S" ]] || exit 1
fi

echo "==> criando a VM $VM_NAME ($MACHINE_TYPE, $ZONE), excluída em $TERMINATION_TIME"
gcloud compute instances create "$VM_NAME" \
  --zone "$ZONE" \
  --machine-type "$MACHINE_TYPE" \
  --image-family debian-12 --image-project debian-cloud \
  --boot-disk-size 20GB \
  --tags "$FIREWALL_RULE" \
  --metadata-from-file startup-script="$HERE/startup.sh" \
  --termination-time "$TERMINATION_TIME" \
  --instance-termination-action DELETE

EXTERNAL_HOST=localhost
if [[ -n "$ALLOWED_CIDR" ]]; then
  echo "==> liberando a porta 9092 para $ALLOWED_CIDR"
  gcloud compute firewall-rules create "$FIREWALL_RULE" \
    --allow tcp:9092 --source-ranges "$ALLOWED_CIDR" --target-tags "$FIREWALL_RULE"
  EXTERNAL_HOST="$(gcloud compute instances describe "$VM_NAME" --zone "$ZONE" \
    --format 'get(networkInterfaces[0].accessConfigs[0].natIP)')"
fi

echo "==> esperando o Docker ficar pronto na VM"
for _ in $(seq 60); do
  if ssh_vm "test -f /run/ods-docker-ready" 2>/dev/null; then
    break
  fi
  sleep 10
done
ssh_vm "test -f /run/ods-docker-ready"

echo "==> copiando o I9 (sem o dataset)"
tar -C "$I9_DIR" -cz \
  --exclude "PPE detection f.v9i.coco" --exclude "__pycache__" --exclude ".env" . \
  | gcloud compute ssh "$VM_NAME" --zone "$ZONE" --quiet \
      --command "rm -rf ~/i9 && mkdir -p ~/i9 && tar -xz -C ~/i9"

echo "==> subindo Kafka + I9"
ssh_vm "cd ~/i9 && echo KAFKA_EXTERNAL_HOST=$EXTERNAL_HOST > .env && sudo docker compose up -d --build && sudo docker compose ps"

cat <<EOF

Pronto. A VM é excluída automaticamente em $TERMINATION_TIME.
  logs do I9:    gcloud compute ssh $VM_NAME --zone $ZONE -- 'cd ~/i9 && sudo docker compose logs -f i9'
  teste:         gcloud compute ssh $VM_NAME --zone $ZONE -- 'cd ~/i9 && sudo docker compose exec i9 python3 tools/kafka_cli.py send examples/i1_detections.json'
  excluir antes: ./deploy/gce/teardown.sh
EOF
if [[ "$EXTERNAL_HOST" != localhost ]]; then
  echo "  broker externo: $EXTERNAL_HOST:9092 (só para $ALLOWED_CIDR)"
fi
