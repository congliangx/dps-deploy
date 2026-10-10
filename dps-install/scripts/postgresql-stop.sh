#!/usr/bin/env bash
set -euo pipefail
ROOT=/raid/vince/deploy
COMPOSE="$ROOT/dps-install/config/postgresql/compose.yaml"
# Stop the container; do not delete volumes or data.
docker compose -p dps-postgresql -f "$COMPOSE" stop
