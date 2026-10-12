#!/usr/bin/env bash
# Explicit DPS 0.9 topology registration only. Leaves topology inactive.
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
umask 077
base=$DPS_RUNTIME_ROOT
export DPSCTL_CREDENTIALS_PATH="${DPSCTL_CREDENTIALS_PATH:-$base/dps-install/config/dpsctl/credentials.yaml}"
export DPSCTL_LOG_FILE="${DPSCTL_LOG_FILE:-$base/verification/logs/dpsctl.log}"
topology="$base/dps-install/config/topology-4rack-dps09.json"
[[ $# -eq 0 ]] || { printf '%s\n' 'Usage: import-topology.sh' >&2; exit 2; }
[[ -s "$DPSCTL_CREDENTIALS_PATH" ]] || {
  printf '%s\n' "Authenticate with dpsctl login first, using DPSCTL_CREDENTIALS_PATH=$DPSCTL_CREDENTIALS_PATH" >&2
  exit 1
}
python3 - "$topology" <<'CHECK'
import json,sys,os
x=json.load(open(sys.argv[1],encoding='utf-8'))
if x.get('Policies'):
 raise SystemExit('DPS 0.9 rejects legacy topology Policies; use the prepared DPS 0.9 input.')
if x['Topology']['Name']!=os.environ['DPS_TOPOLOGY_NAME']:
 raise SystemExit('Unexpected topology name')
CHECK
# Ensure the SDK power-shelf specification exists before semantic validation.
"$DPS_SOURCE_ROOT/dps-install/scripts/register-devices.sh"
# Semantic validation is read-only and must pass before topology inventory writes.
validation="$(dpsctl --output json topology validate "$topology")"
printf '%s\n' "$validation"
printf '%s' "$validation" | python3 -c 'import json,sys,os; x=json.load(sys.stdin); sys.exit(0 if x.get("status",{}).get("ok") is True else 1)'
# Import registers entities/hierarchy. It does not activate a topology or apply power.
# An existing topology name is rejected by dpsctl; do not replace/reset it here.
result="$(dpsctl --output json topology import "$topology")"
printf '%s\n' "$result"
printf '%s' "$result" | python3 -c 'import json,sys,os; x=json.load(sys.stdin); sys.exit(0 if x.get("status",{}).get("ok") is True else 1)'

# Verify/correct persisted agent routing through the explicit inactive update API.
"$DPS_SOURCE_ROOT/dps-install/scripts/update-topology.sh"
