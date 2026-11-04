#!/bin/bash
# Exclui a VM do I9 (e o disco) e a regra de firewall da porta 9092.
# A VM some sozinha na hora de término, mas a regra de firewall não: rode este
# script ao final para não deixar nada para trás.
set -uo pipefail

VM_NAME="${VM_NAME:-ods-i9}"
ZONE="${ZONE:-southamerica-east1-a}"
FIREWALL_RULE="${VM_NAME}-kafka"

gcloud compute instances delete "$VM_NAME" --zone "$ZONE" --quiet \
  || echo "VM $VM_NAME não encontrada (talvez já excluída na hora de término)"
gcloud compute firewall-rules delete "$FIREWALL_RULE" --quiet \
  || echo "regra de firewall $FIREWALL_RULE não encontrada"
