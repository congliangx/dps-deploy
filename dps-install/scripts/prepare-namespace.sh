#!/usr/bin/env bash
set -euo pipefail
umask 077
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
[[ $# -eq 0 ]] || { echo 'Usage: prepare-namespace.sh [deployment overrides]' >&2; exit 2; }
python3 - <<'PYTHON'
import json,os,socket,subprocess
from pathlib import Path
import yaml
from deployment_context import load_context
ctx=load_context();c=ctx.runtime_path('dps-install/config');ns=ctx.settings['namespace']
k=['kubectl','--context',ctx.settings['kube_context']]
v=yaml.safe_load((c/'values.yaml').read_text())
files=[c/f for f in ['postgresql-secret.yaml','postgresql-ca-secret.yaml','bmc-shared-secret.yaml','bmc-ca-secret.yaml']]
files += [c/'tls'/f for f in ['dps-server-tls-secret.yaml','dps-agent-tls-secret.yaml','dps-ingress-tls-secret.yaml','dps-jwt-keys-secret.yaml']]
if v.get('dps',{}).get('ldap',{}).get('enabled'):
 files += [c/'ldap'/f for f in ['dps-ldap-bind-secret.yaml','dps-ldap-ca-secret.yaml','dps-ldap-client-tls-secret.yaml']]
if v.get('dps',{}).get('prs',{}).get('enabled'):
 files += [c/'prs'/f for f in ['s3-secret.yaml','dps-auth-secret.yaml']]
# Verify every local Secret's namespace before making any cluster change.
for f in files:
 obj=yaml.safe_load(f.read_text())
 if obj.get('kind')!='Secret' or obj['metadata'].get('namespace')!=ns:
  raise SystemExit('Secret input namespace/type conflicts with deployment.yaml: '+f.name)
r=subprocess.run([*k,'get','namespace',ns],capture_output=True)
if r.returncode:subprocess.run([*k,'create','namespace',ns],check=True)
for f in files:subprocess.run([*k,'--namespace',ns,'apply','--server-side','--field-manager=dps-prerequisites','-f',f],check=True)
p=Path('/etc/hosts');text=p.read_text();missing=[];ip=ctx.settings['host_ip']
for host in [ctx.settings['api_name'],ctx.settings['ui_name']]:
 try:addresses={r[4][0] for r in socket.getaddrinfo(host,None,socket.AF_INET)}
 except socket.gaierror:addresses=set()
 if addresses and addresses!={ip}:raise SystemExit('Hostname resolves to another address: '+host)
 if not addresses:missing.append(host)
if missing:
 backup=ctx.runtime_path('verification/archive/prerequisites/hosts.before-dps');backup.parent.mkdir(parents=True,exist_ok=True)
 if not backup.exists():backup.write_text(text);backup.chmod(0o600)
 with p.open('a') as f:f.write('\n'+ip+' '+' '.join(missing)+' # DPS '+ns+'\n')
print('External Secrets applied to '+ns+'; project hostnames checked.')
PYTHON
