#!/bin/bash
# Atualiza o código do I9 numa VM já criada pelo deploy.sh: copia o I9 (sem o
# dataset) por cima e reconstrói só o container `i9`. O Kafka e os dados dele
# não são tocados.
#
#   cd I9 && ./deploy/gce/update.sh
set -euo pipefail

VM_NAME="${VM_NAME:-ods-i9}"
ZONE="${ZONE:-southamerica-east1-a}"

HERE="$(cd "$(dirname "$0")" && pwd)"
I9_DIR="$(cd "$HERE/../.." && pwd)"

echo "==> copiando o I9 para $VM_NAME"
tar -C "$I9_DIR" -cz \
  --exclude "PPE detection f.v9i.coco" --exclude "__pycache__" --exclude ".env" . \
  | gcloud compute ssh "$VM_NAME" --zone "$ZONE" --quiet --command "mkdir -p ~/i9 && tar -xz -C ~/i9"

echo "==> reconstruindo o container i9"
gcloud compute ssh "$VM_NAME" --zone "$ZONE" --quiet \
  --command "cd ~/i9 && sudo docker compose up -d --build i9 && sudo docker compose ps"
