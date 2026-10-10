#!/usr/bin/env bash
set -euo pipefail
cd /raid/vince/deploy
source dps-install/config/dps-env.sh
kubectl --context "$DPS_KUBE_CONTEXT" create namespace dps --dry-run=client -o yaml | kubectl --context "$DPS_KUBE_CONTEXT" apply -f -
for dps_secret_file in \
  dps-install/config/postgresql-secret.yaml \
  dps-install/config/postgresql-ca-secret.yaml \
  dps-install/config/bmc-shared-secret.yaml \
  dps-install/config/bmc-ca-secret.yaml \
  dps-install/config/tls/dps-server-tls-secret.yaml \
  dps-install/config/tls/dps-agent-tls-secret.yaml \
  dps-install/config/tls/dps-ingress-tls-secret.yaml \
  dps-install/config/tls/dps-jwt-keys-secret.yaml; do
  kubectl --context "$DPS_KUBE_CONTEXT" --namespace dps apply --server-side --field-manager=dps-prerequisites -f "$dps_secret_file"
done
# External LDAP credentials and CA are required only for the LDAP authenticator.
if python3 - <<'LDAP_ENABLED'
from pathlib import Path
import sys,yaml
v=yaml.safe_load(Path('/raid/vince/deploy/dps-install/config/values.yaml').read_text())
sys.exit(0 if v.get('dps',{}).get('ldap',{}).get('enabled') is True else 1)
LDAP_ENABLED
then
  for dps_ldap_secret in dps-install/config/ldap/dps-ldap-bind-secret.yaml dps-install/config/ldap/dps-ldap-ca-secret.yaml dps-install/config/ldap/dps-ldap-client-tls-secret.yaml; do
    test -s "$dps_ldap_secret"
    kubectl --context "$DPS_KUBE_CONTEXT" --namespace dps apply --server-side --field-manager=dps-prerequisites -f "$dps_ldap_secret"
  done
fi
# PRS credentials remain external to Helm values.
if python3 - <<'PRS_ENABLED'
from pathlib import Path
import sys,yaml
v=yaml.safe_load(Path('/raid/vince/deploy/dps-install/config/values.yaml').read_text())
sys.exit(0 if v['dps'].get('prs',{}).get('enabled') else 1)
PRS_ENABLED
then
  for dps_prs_secret in dps-install/config/prs/s3-secret.yaml dps-install/config/prs/dps-auth-secret.yaml; do
    test -s "$dps_prs_secret"
    kubectl --context "$DPS_KUBE_CONTEXT" --namespace dps apply --server-side --field-manager=dps-prerequisites -f "$dps_prs_secret"
  done
fi
python3 - <<'PY'
from pathlib import Path
import socket
for host in ['api.dps.lab','ui.dps.lab']:
 try:
  addresses={r[4][0] for r in socket.getaddrinfo(host,None,socket.AF_INET)}
 except socket.gaierror:addresses=set()
 if addresses and addresses!={'10.6.131.43'}:raise RuntimeError(host+' already resolves to another address')
p=Path('/etc/hosts');s=p.read_text()
missing=[h for h in ['api.dps.lab','ui.dps.lab'] if h not in [w for line in s.splitlines() for w in line.split('#')[0].split()[1:]]]
if missing:
 backup=Path('/raid/vince/deploy/verification/archive/prerequisites/hosts.before-dps')
 if not backup.exists():backup.write_text(s)
 with p.open('a') as f:f.write('\n10.6.131.43 '+' '.join(missing)+' # DPS lab\n')
print('DPS lab hostnames resolve on L20-12.')
PY
kubectl --context "$DPS_KUBE_CONTEXT" get secrets --namespace dps
