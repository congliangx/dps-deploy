#!/usr/bin/env bash
set -euo pipefail
for dps_arg in "$@"; do
  if [[ "$dps_arg" == --help || "$dps_arg" == -h ]]; then
    printf '%s\n' 'Usage: postgresql-stop.sh [deployment options]'
    exit 0
  fi
done
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
[[ $# -eq 0 ]] || { printf '%s\n' 'Unexpected argument; use --help.' >&2; exit 2; }
COMPOSE_PROJECT=$(dps_compose_project "$DPS_PG_CONTAINER" "$DPS_PG_PROJECT")
ROOT=$DPS_RUNTIME_ROOT
COMPOSE="$ROOT/dps-install/config/postgresql/compose.yaml"
# Stop the container; do not delete volumes or data.
docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE" stop
