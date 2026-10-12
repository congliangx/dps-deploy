#!/usr/bin/env bash
set -euo pipefail
for dps_arg in "$@"; do
  if [[ "$dps_arg" == --help || "$dps_arg" == -h ]]; then
    printf '%s\n' 'Usage: register-devices.sh [deployment options]'
    exit 0
  fi
done
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
umask 077
base=$DPS_RUNTIME_ROOT
export DPSCTL_CREDENTIALS_PATH="${DPSCTL_CREDENTIALS_PATH:-$base/dps-install/config/dpsctl/credentials.yaml}"
export DPSCTL_LOG_FILE="${DPSCTL_LOG_FILE:-$base/verification/logs/dpsctl.log}"
[[ $# -eq 0 ]] || { printf '%s\n' 'This script accepts no arguments.' >&2; exit 2; }
[[ -s "$DPSCTL_CREDENTIALS_PATH" ]] || { printf '%s\n' 'Authenticate with dpsctl login using the project credentials path first.' >&2; exit 1; }
# Add the SDK shelf model only when absent. Never overwrite a mismatched model.
python3 - "$DPS_SOURCE_ROOT/dps-install/config/gb300-power-shelf-devices.yaml" <<'PYTHON'
import json,subprocess,sys
model='PowerSupply95_33000W'
def registry():
 r=subprocess.run(['dpsctl','--output','json','device','list'],capture_output=True,text=True,check=True)
 return json.loads(r.stdout)
def check(rows):
 matches=[d for d in rows if d.get('type')=='PowerSupply' and d.get('model')==model]
 if not matches: return False
 if len(matches)!=1: raise SystemExit('Duplicate shelf model in registry; manual review required.')
 spec=matches[0].get('Spec',{}).get('PowerSupply',{})
 if spec.get('max_load_watts')!=33000 or spec.get('efficiency_factor')!=0.95:
  raise SystemExit('Existing shelf model differs from 33000 W / 0.95; refusing to overwrite it.')
 return True
if check(registry()):
 print('Existing 33000 W / 0.95 GB300 shelf model verified; no registry write performed.')
else:
 r=subprocess.run(['dpsctl','--output','json','device','upsert',sys.argv[1]],capture_output=True,text=True,check=True)
 x=json.loads(r.stdout)
 if x.get('status',{}).get('ok') is not True: raise SystemExit('Device registration did not return status.ok=true.')
 if not check(registry()): raise SystemExit('Registered shelf model could not be verified.')
 print('Registered and verified only the custom GB300 shelf model (33000 W / 0.95).')
PYTHON
