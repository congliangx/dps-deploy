#!/usr/bin/env bash
set -euo pipefail
for dps_arg in "$@"; do
  if [[ "$dps_arg" == --help || "$dps_arg" == -h ]]; then
    printf '%s\n' 'Usage: ldap-status.sh [deployment options]'
    exit 0
  fi
done
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
[[ $# -eq 0 ]] || { printf '%s\n' 'Unexpected argument; use --help.' >&2; exit 2; }
COMPOSE_PROJECT=$(dps_compose_project "$DPS_LDAP_CONTAINER" "$DPS_LDAP_PROJECT")
docker compose -p "$COMPOSE_PROJECT" -f "$DPS_RUNTIME_ROOT/dps-install/config/ldap/compose.yaml" ps
docker inspect --format 'health={{.State.Health.Status}} restart={{.HostConfig.RestartPolicy.Name}}' "$DPS_LDAP_CONTAINER"
