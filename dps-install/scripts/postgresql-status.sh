#!/usr/bin/env bash
set -euo pipefail
ROOT=/raid/vince/deploy
COMPOSE="$ROOT/dps-install/config/postgresql/compose.yaml"
docker compose -p dps-postgresql -f "$COMPOSE" ps
docker exec -u postgres dps-postgresql psql -X -v ON_ERROR_STOP=1 -U postgres -d dps -c "SELECT version(), datname, pg_get_userbyid(datdba) AS owner FROM pg_database WHERE datname = 'dps';"
