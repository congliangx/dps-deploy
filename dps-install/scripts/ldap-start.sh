#!/usr/bin/env bash
set -euo pipefail
for dps_arg in "$@"; do
  if [[ "$dps_arg" == --help || "$dps_arg" == -h ]]; then
    printf '%s\n' 'Usage: ldap-start.sh [deployment options]'
    exit 0
  fi
done
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
[[ $# -eq 0 ]] || { printf '%s\n' 'Unexpected argument; use --help.' >&2; exit 2; }
COMPOSE_PROJECT=$(dps_compose_project "$DPS_LDAP_CONTAINER" "$DPS_LDAP_PROJECT")
ROOT=$DPS_RUNTIME_ROOT
COMPOSE="$ROOT/dps-install/config/ldap/compose.yaml"
docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE" config --quiet
docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE" up -d
for attempt in $(seq 1 60); do
  state=$(docker inspect --format '{{.State.Health.Status}}' "$DPS_LDAP_CONTAINER")
  if [ "$state" = healthy ]; then
    docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE" ps
    exit 0
  fi
  sleep 2
done
echo "OpenLDAP did not become healthy; inspect docker logs $DPS_LDAP_CONTAINER." >&2
exit 1
