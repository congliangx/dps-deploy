#!/usr/bin/env bash
set -euo pipefail
ROOT=/raid/vince/deploy
COMPOSE="$ROOT/dps-install/config/postgresql/compose.yaml"
umask 077
BACKUP_DIR="$ROOT/dps-install/data/postgresql-backups"
mkdir -p "$BACKUP_DIR"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$BACKUP_DIR/dps-$stamp.dump"
[ ! -e "$target" ] || { echo 'Backup already exists.' >&2; exit 1; }
docker exec -u postgres dps-postgresql pg_dump -U postgres -d dps --format=custom > "$target.tmp"
docker exec -i -u postgres dps-postgresql pg_restore --list < "$target.tmp" >/dev/null
mv "$target.tmp" "$target"
echo "Backup saved: $target"
