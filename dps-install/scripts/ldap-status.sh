#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
COMPOSE_PROJECT=$(dps_compose_project "$DPS_LDAP_CONTAINER" "$DPS_LDAP_PROJECT")
docker compose -p "$COMPOSE_PROJECT" -f "$DPS_RUNTIME_ROOT/dps-install/config/ldap/compose.yaml" ps
docker inspect --format 'health={{.State.Health.Status}} restart={{.HostConfig.RestartPolicy.Name}}' "$DPS_LDAP_CONTAINER"
