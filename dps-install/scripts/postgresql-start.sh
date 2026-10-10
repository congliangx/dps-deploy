#!/usr/bin/env bash
set -euo pipefail
ROOT=/raid/vince/deploy
COMPOSE="$ROOT/dps-install/config/postgresql/compose.yaml"
# This starts the existing persistent database; it never resets data.
docker compose -p dps-postgresql -f "$COMPOSE" config --quiet
docker compose -p dps-postgresql -f "$COMPOSE" up -d
for attempt in $(seq 1 60); do
  state=$(docker inspect --format '{{.State.Health.Status}}' dps-postgresql)
  if [ "$state" = healthy ]; then
    docker compose -p dps-postgresql -f "$COMPOSE" ps
    exit 0
  fi
  sleep 2
done
echo 'PostgreSQL did not become healthy; inspect docker logs dps-postgresql.' >&2
exit 1
