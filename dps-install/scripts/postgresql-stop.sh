#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
COMPOSE_PROJECT=$(dps_compose_project "$DPS_PG_CONTAINER" "$DPS_PG_PROJECT")
ROOT=$DPS_RUNTIME_ROOT
COMPOSE="$ROOT/dps-install/config/postgresql/compose.yaml"
# Stop the container; do not delete volumes or data.
docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE" stop
