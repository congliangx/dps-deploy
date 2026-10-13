#!/usr/bin/env bash
# Recover an existing shared HTTPS UI proxy using the repository deployment context.
set -euo pipefail
umask 077

usage() {
  printf '%s\n' 'Usage: shared-ui-start.sh [deployment options] [--check|--help]
  no action      Validate and start the already-configured shared HTTPS proxy.
  --check        Validate and check the running proxy; do not start it.
  --config FILE  Select deployment.yaml (default: this repository).
  --runtime-root DIR  Override the runtime directory.
  --help         Show help without reading configuration or contacting services.
Requires runtime/dps-install/config/access/shared-ui/{compose.yaml,nginx.conf,access.json}
and the existing TLS files. This is a recovery tool, not initial proxy installation.
Fixed image sources come from source/dps-install/config/artifact-sources.json.
It preserves existing identity and refuses another instance or stale UI Service.
'
}

for dps_arg in "$@"; do
  case "$dps_arg" in --help|-h) usage; exit 0 ;; esac
done
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
if (( $# > 1 )); then usage >&2; exit 2; fi
case "${1:-}" in
  "") action=start ;;
  --check) action=check ;;
  *) usage >&2; exit 2 ;;
esac

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for required in docker python3 openssl curl; do
  command -v "$required" >/dev/null 2>&1 || fail "Required command missing: $required"
done
docker compose version >/dev/null 2>&1 || fail "Docker Compose is unavailable."
docker info >/dev/null 2>&1 || fail "Docker is not running or accessible. Check: systemctl status docker"

access_dir="$DPS_RUNTIME_ROOT/dps-install/config/access/shared-ui"
params="$(python3 - "$access_dir" <<'PREFLIGHT'
import hashlib, ipaddress, json, os, re, subprocess, sys
from pathlib import Path
from urllib.parse import urlparse
import yaml
base=Path(sys.argv[1])
def require(ok,message):
    if not ok: raise SystemExit('ERROR: '+message)
for name in ['compose.yaml','nginx.conf','access.json']:
    require((base/name).is_file(),'Missing saved configuration: '+name)
metadata=json.loads((base/'access.json').read_text())
source=Path(os.environ['DPS_SOURCE_ROOT'])
runtime=Path(os.environ['DPS_RUNTIME_ROOT']).resolve()
pins=json.loads((source/'dps-install/config/artifact-sources.json').read_text())['images']
expected_pin=next(row['image_digest'] for row in pins if row['name']=='nginx-proxy')
require(metadata.get('image_digest')==expected_pin,'Saved proxy image differs from the canonical artifact source; review the configuration.')
expected_project=os.environ['DPS_RELEASE']+'-ui-access'
require(metadata.get('compose_project')==expected_project and metadata.get('container')==expected_project,
        'Shared proxy belongs to a different release; preserve the existing instance.')
document=yaml.safe_load((base/'compose.yaml').read_text())
require(set(document.get('services',{}))=={'ui-access'},'Compose must contain only the shared UI proxy.')
service=document['services']['ui-access']
project=metadata['compose_project']; container=metadata['container']
require(service.get('container_name')==container,'Container name does not match access.json.')
require(service.get('network_mode')=='host','Unexpected proxy network configuration.')
require(service.get('labels',{}).get('com.nvidia.dps.runtime-root')==str(runtime),
        'Compose runtime ownership differs from deployment.yaml.')
pin=metadata['image_digest']
require(re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}',pin) is not None,'Image must use a fixed SHA256 digest.')
require(service.get('image')==pin,'Compose image does not match access.json.')
image=json.loads(subprocess.check_output(['docker','image','inspect',pin],text=True))[0]
require(pin in image.get('RepoDigests',[]),'Cached image RepoDigest mismatch.')
require(image['Id']==metadata['image_id'],'Cached image ID mismatch.')
mounts={}
for value in service.get('volumes',[]):
    require(isinstance(value,str),'Unexpected volume configuration.')
    source,target,mode=value.rsplit(':',2)
    source_path=Path(source)
    if not source_path.is_absolute(): source_path=base/source_path
    mounts[target]=(source_path.resolve(),mode)
required=['/etc/nginx/nginx.conf','/etc/dps-ui-tls/ingress.crt','/etc/dps-ui-tls/ingress.key','/etc/dps-ui-tls/ca.crt']
for target in required:
    require(target in mounts,'Missing mounted file: '+target)
    path,mode=mounts[target]
    require(mode=='ro' and path.is_file(),'Mounted file must exist and be read-only: '+target)
require(mounts['/etc/nginx/nginx.conf'][0].resolve()==(base/'nginx.conf').resolve(),'Nginx configuration points to a different directory.')
ca=mounts['/etc/dps-ui-tls/ca.crt'][0]
certificate=mounts['/etc/dps-ui-tls/ingress.crt'][0]
require(hashlib.sha256(ca.read_bytes()).hexdigest()==metadata['public_ca_sha256'],'Public CA differs from the saved identity.')
url=metadata['url'].rstrip('/'); parsed=urlparse(url)
require(parsed.scheme=='https' and parsed.hostname and parsed.port and not parsed.username and not parsed.password,'Invalid saved HTTPS URL.')
require(parsed.hostname==os.environ['DPS_HOST_IP'],'Proxy host differs from deployment.yaml; review before changing the installed instance.')
service_name=os.environ['DPS_FULLNAME']+'-ui'
cluster_service=json.loads(subprocess.check_output([
    'kubectl','--kubeconfig',os.environ['KUBECONFIG'],'--context',os.environ['DPS_KUBE_CONTEXT'],
    '-n',os.environ['DPS_NAMESPACE'],'--request-timeout=10s','get','service',service_name,'-o','json'],text=True))
expected_uid=service.get('labels',{}).get('com.nvidia.dps.source-service-uid')
require(cluster_service['metadata']['uid']==expected_uid,'UI Service identity changed; review the proxy configuration.')
upstream=urlparse(metadata['upstream'])
require(upstream.scheme=='http' and upstream.hostname==cluster_service['spec']['clusterIP'],
        'UI Service ClusterIP changed; review the proxy configuration.')
require(any(port['port']==upstream.port for port in cluster_service['spec']['ports']),
        'Saved UI Service port is no longer available.')
nginx=(base/'nginx.conf').read_text()
require(re.search(r'proxy_pass\s+'+re.escape(metadata['upstream'])+r'\s*;',nginx) is not None,
        'Nginx upstream differs from saved metadata.')
require(re.search(r'listen\s+'+re.escape(parsed.hostname)+':'+str(parsed.port)+r'\s+ssl\s*;',nginx) is not None,
        'Nginx HTTPS listener differs from saved metadata.')
try:
    ipaddress.ip_address(parsed.hostname); verify_option='-verify_ip'
except ValueError: verify_option='-verify_hostname'
existing=subprocess.run(['docker','inspect',container],capture_output=True,text=True)
if existing.returncode==0:
    record=json.loads(existing.stdout)[0]; labels=record['Config'].get('Labels') or {}
    require(labels.get('com.docker.compose.project')==project,'Existing container belongs to another Compose project.')
    require(labels.get('com.nvidia.dps.purpose')=='shared-ui-access','Existing container is not the managed shared UI proxy.')
    expected_root=service.get('labels',{}).get('com.nvidia.dps.runtime-root')
    require(expected_root and labels.get('com.nvidia.dps.runtime-root')==expected_root,'Existing container runtime ownership differs.')
for value in [project,container,url,str(ca),str(certificate),verify_option,parsed.hostname]:
    require('\n' not in value,'Invalid configuration value.')
    print(value)
PREFLIGHT
)"
mapfile -t settings <<< "$params"
(( ${#settings[@]} == 7 )) || fail "Could not read saved UI configuration."
project="${settings[0]}"; container="${settings[1]}"; url="${settings[2]}"
ca="${settings[3]}"; certificate="${settings[4]}"
verify_option="${settings[5]}"; host="${settings[6]}"
compose=(docker compose -p "$project" -f "$access_dir/compose.yaml")

"${compose[@]}" config --quiet
openssl verify -CAfile "$ca" "$verify_option" "$host" "$certificate"
printf 'Saved configuration, fixed image digest and TLS identity verified.\n'

if [[ "$action" == start ]]; then
  if [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null || true)" == true ]]; then
    docker exec "$container" nginx -t
  else
    "${compose[@]}" run --rm --no-deps --entrypoint nginx ui-access -t
  fi
  "${compose[@]}" up -d ui-access
else
  [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null || true)" == true ]] ||
    fail "Proxy is not running. Execute this script without --check to start it."
  docker exec "$container" nginx -t
fi

check_https() {
  curl --noproxy '*' --fail --silent --show-error --cacert "$ca" \
    --connect-timeout 3 --max-time 8 -o /dev/null "$url/" &&
  curl --noproxy '*' --fail --silent --show-error --cacert "$ca" \
    --connect-timeout 3 --max-time 8 "$url/api/health" |
    python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("status")=="OK" else 1)'
}
attempts=1
[[ "$action" == start ]] && attempts=10
for (( attempt=1; attempt<=attempts; attempt++ )); do
  if check_https >/dev/null 2>&1; then
    printf 'Shared DPS UI is available: %s\n' "$url"
    "${compose[@]}" ps
    exit 0
  fi
  (( attempt < attempts )) && sleep 2
done
printf 'ERROR: HTTPS page or UI health endpoint is unavailable: %s\n' "$url" >&2
printf 'Inspect the proxy with: docker logs --tail=60 %q\n' "$container" >&2
printf 'If the upstream UI is not ready, check Kubernetes and retry later.\n' >&2
exit 1
