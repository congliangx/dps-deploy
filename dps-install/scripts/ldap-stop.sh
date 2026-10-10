#!/usr/bin/env bash
set -euo pipefail
# Stop only this independent LDAP service; preserve directory data and configuration.
docker compose -p dps-openldap -f /raid/vince/deploy/dps-install/config/ldap/compose.yaml stop
