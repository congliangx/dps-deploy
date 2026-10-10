#!/usr/bin/env bash
set -euo pipefail
ROOT=/raid/vince/deploy
COMPOSE="$ROOT/dps-install/config/ldap/compose.yaml"
docker compose -p dps-openldap -f "$COMPOSE" config --quiet
docker compose -p dps-openldap -f "$COMPOSE" up -d
for attempt in $(seq 1 60); do
  state=$(docker inspect --format '{{.State.Health.Status}}' dps-openldap)
  if [ "$state" = healthy ]; then
    docker compose -p dps-openldap -f "$COMPOSE" ps
    exit 0
  fi
  sleep 2
done
echo 'OpenLDAP did not become healthy; inspect docker logs dps-openldap.' >&2
exit 1
