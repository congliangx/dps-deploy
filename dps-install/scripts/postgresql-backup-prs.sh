#!/usr/bin/env bash
set -euo pipefail
for dps_arg in "$@"; do
  if [[ "$dps_arg" == --help || "$dps_arg" == -h ]]; then
    printf '%s\n' 'Usage: postgresql-backup-prs.sh [deployment options]'
    exit 0
  fi
done
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
[[ $# -eq 0 ]] || { printf '%s\n' 'Unexpected argument; use --help.' >&2; exit 2; }
ROOT=$DPS_RUNTIME_ROOT
umask 077
BACKUP_DIR="$ROOT/dps-install/data/postgresql-backups"
mkdir -p "$BACKUP_DIR"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
for db in dps_prs_config dps_prs_config_staged dps_prs_controller; do
  target="$BACKUP_DIR/$db-$stamp.dump"
  [ ! -e "$target" ] || { echo 'Backup already exists.' >&2; exit 1; }
  docker exec -u postgres "$DPS_PG_CONTAINER" pg_dump -U postgres -d "$db" --format=custom > "$target.tmp"
  docker exec -i -u postgres "$DPS_PG_CONTAINER" pg_restore --list < "$target.tmp" >/dev/null
  mv "$target.tmp" "$target"
  echo "Backup saved: $target"
done
