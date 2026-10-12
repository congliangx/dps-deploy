#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
ROOT=$DPS_RUNTIME_ROOT
umask 077
mkdir -p "$ROOT/dps-install/data/ldap-backups"
target="$ROOT/dps-install/data/ldap-backups/ldap-$(date -u +%Y%m%dT%H%M%SZ).ldif"
[ ! -e "$target" ] || { echo 'Backup already exists.' >&2; exit 1; }
# MDB supports a consistent read transaction while slapd serves requests.
docker exec "$DPS_LDAP_CONTAINER" slapcat -f /run/ldap-config/slapd.conf -b 'dc=dps,dc=lab' > "$target.tmp"
[ -s "$target.tmp" ] || { rm -f "$target.tmp"; echo 'LDAP backup empty.' >&2; exit 1; }
mv "$target.tmp" "$target"
echo "LDAP backup saved: $target"
