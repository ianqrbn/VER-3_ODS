#!/bin/bash
# Startup script da VM (roda como root a cada boot): instala e liga o Docker.
# O deploy.sh espera o arquivo de pronto antes de copiar o I9.
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
touch /run/ods-docker-ready
