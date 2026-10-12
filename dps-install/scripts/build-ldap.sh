#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
[[ $# -eq 0 ]] || { echo 'Usage: build-ldap.sh [deployment overrides]' >&2; exit 2; }
exec python3 "$DPS_SOURCE_ROOT/dps-install/scripts/download-artifacts.py" --component ldap
