#!/usr/bin/env bash
# Authenticate the documented LDAP account without putting passwords on argv.
set -euo pipefail
for dps_arg in "$@"; do
  if [[ "$dps_arg" == --help || "$dps_arg" == -h ]]; then
    printf '%s\n' 'Usage: dps-login.sh [deployment options]'
    exit 0
  fi
done
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
[[ $# -eq 0 ]] || { printf '%s\n' 'Unexpected argument; use --help.' >&2; exit 2; }
umask 077
python3 - <<'PYTHON'
import json, os, subprocess
from pathlib import Path
import yaml
c=Path(os.environ['DPS_RUNTIME_ROOT'])/'dps-install/config'
v=yaml.safe_load((c/'values.yaml').read_text())
if v['dps']['auth']['authenticatorType']!='ldap' or not v['dps']['ldap']['enabled']:
 raise SystemExit('Current deployment input must use LDAP authentication')
account=json.loads((c/'dps-access.json').read_text())
r=subprocess.run(['dpsctl','--no-retry','login','--username',account['username'],'--password-stdin'],
 input=account['password']+'\n',capture_output=True,text=True,timeout=90)
text=r.stdout.strip()
start=text.find('{')
try:response=json.loads(text[start:]) if start>=0 else {}
except ValueError:response={}
if r.returncode or response.get('status',{}).get('ok') is not True:
 raise SystemExit('LDAP login failed; inspect the private project dpsctl log')
p=Path(os.environ['DPSCTL_CREDENTIALS_PATH'])
p.chmod(0o600)
print('LDAP login successful for '+account['username']+'; credentials saved privately in '+str(p))
PYTHON
