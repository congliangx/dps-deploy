#!/usr/bin/env bash
set -euo pipefail
docker compose -p dps-openldap -f /raid/vince/deploy/dps-install/config/ldap/compose.yaml ps
docker inspect --format 'health={{.State.Health.Status}} restart={{.HostConfig.RestartPolicy.Name}}' dps-openldap
