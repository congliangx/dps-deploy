#!/usr/bin/env bash
set -euo pipefail
ROOT=/raid/vince/deploy
umask 077
target="$ROOT/dps-install/data/ldap-backups/ldap-$(date -u +%Y%m%dT%H%M%SZ).ldif"
[ ! -e "$target" ] || { echo 'Backup already exists.' >&2; exit 1; }
# MDB supports a consistent read transaction while slapd serves requests.
docker exec dps-openldap slapcat -f /run/ldap-config/slapd.conf -b 'dc=dps,dc=lab' > "$target.tmp"
[ -s "$target.tmp" ] || { rm -f "$target.tmp"; echo 'LDAP backup empty.' >&2; exit 1; }
mv "$target.tmp" "$target"
echo "LDAP backup saved: $target"
