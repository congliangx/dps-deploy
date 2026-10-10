#!/usr/bin/env bash
# Manually install the saved DPS 0.9 chart; never invoke the SDK.
set -euo pipefail
umask 077
cd /raid/vince/deploy
source dps-install/config/dps-env.sh
systemctl is-active --quiet k3s
kubectl --context "$DPS_KUBE_CONTEXT" wait --for=condition=Ready node "$DPS_KUBE_NODE" --timeout=60s
python3 - <<'CHECK'
from pathlib import Path
import os,subprocess,json,yaml,hashlib
B=Path('/raid/vince/deploy')
chart=B/'dps-install/packages/dps-0.9.0.tgz'
assert hashlib.sha256(chart.read_bytes()).hexdigest()=='2fc7b6e098b17085bf9aaf010d86dfeaf62677fd0f80bb4c2702e91b0b3fd6ef','Chart checksum mismatch'
v=yaml.safe_load((B/'dps-install/config/values.yaml').read_text())
assert not v['postgresql']['enabled'],'DPS must use the independent PostgreSQL deployment'
if v['dps'].get('prs',{}).get('enabled'):
 assert v['power-steering']['enabled'],'PRS requires the Power Steering subchart'
 assert not v['power-steering']['postgresql']['enabled'],'Power Steering must use the independent PostgreSQL deployment'
 assert v['power-steering']['controller']['cluster']['dps']['auth']['enabled'],'Controller must authenticate to DPS'
 assert not v['power-steering']['controller']['cluster']['dps']['tls']['insecure'] and not v['power-steering']['controller']['cluster']['dps']['tls']['skipVerify'],'Controller DPS TLS verification is required'
 assert v['global']['database']['names']=={'config':'dps_prs_config','configStaged':'dps_prs_config_staged','controller':'dps_prs_controller'},'Unexpected PRS database names'
assert v['dps']['auth']['authenticatorType']=='ldap' and v['dps']['ldap']['enabled'],'LDAP authentication is required by the current deployment plan'
assert not v['dps']['auth'].get('oidc',{}).get('enabled',False),'LDAP and OIDC cannot be enabled together'
assert v['dps']['ldap'].get('defaultRole')=='','Do not grant a default role to LDAP users outside the allowed group'
current=json.loads(subprocess.check_output(['helm','list','--kube-context',os.environ['DPS_KUBE_CONTEXT'],'-n','dps','--all','--filter','^dps$','-o','json'],text=True))
if current:
 assert current[0]['chart']=='dps-0.9.0','Existing DPS release has a different chart'
 assert not current[0]['status'].startswith('pending'),'An existing Helm operation is pending'
CHECK
helm upgrade --install dps dps-install/packages/dps-0.9.0.tgz \
  --kube-context "$DPS_KUBE_CONTEXT" --namespace dps \
  --values dps-install/config/values.yaml --wait --timeout 10m
