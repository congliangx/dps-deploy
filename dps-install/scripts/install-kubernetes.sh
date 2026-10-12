#!/usr/bin/env bash
# Install native K3s on the configured physical host. --download-only never changes system services.
set -euo pipefail
for dps_arg in "$@"; do
  if [[ "$dps_arg" == --help || "$dps_arg" == -h ]]; then
    printf '%s\n' 'Usage: install-kubernetes.sh [deployment options]'
    exit 0
  fi
done
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
umask 077
BASE=$DPS_RUNTIME_ROOT
PACKAGES=$BASE/dps-install/packages/k3s
CONFIG=$BASE/dps-install/config/kubernetes
VERSION=$DPS_K3S_VERSION
[[ "$VERSION" == v1.34.12+k3s1 ]] || { echo 'Add verified artifact checksums before selecting another K3s release.' >&2; exit 1; }
RELEASE="https://github.com/k3s-io/k3s/releases/download/${VERSION//+/%2B}"
MODE=install
if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [--download-only]" >&2; exit 2
fi
if [ "$#" -eq 1 ]; then
  if [ "$1" != --download-only ]; then
    echo "Usage: $0 [--download-only]" >&2; exit 2
  fi
  MODE=download
fi
[ "$(id -u)" -eq 0 ] || { echo "Run this script as root on the configured physical host." >&2; exit 1; }
[ "$(uname -m)" = x86_64 ] || { echo "This release is pinned for x86_64." >&2; exit 1; }
[ -d "$BASE" ] || { echo "Project directory is missing." >&2; exit 1; }
mkdir -p "$PACKAGES"
fetch() {
  name=$1; url=$2; expected=$3
  destination=$PACKAGES/$name
  if [ -e "$destination" ] || [ -L "$destination" ]; then
    [ -f "$destination" ] && [ ! -L "$destination" ] || {
      echo "Preserve unexpected package path: $destination" >&2; return 1;
    }
    actual=$(sha256sum "$destination" | awk '{print $1}')
    [ "$actual" = "$expected" ] || {
      echo "Existing package checksum conflict: $destination" >&2; return 1;
    }
    echo "Verified cached $name"
    return
  fi
  partial=$(mktemp "$PACKAGES/.download-XXXXXXXX")
  if ! curl -fLsS --retry 3 --connect-timeout 15 --max-time 1200 "$url" -o "$partial"; then
    rm -f "$partial"; return 1
  fi
  actual=$(sha256sum "$partial" | awk '{print $1}')
  if [ "$actual" != "$expected" ]; then
    rm -f "$partial"
    echo "SHA256 mismatch: $name" >&2; return 1
  fi
  chmod 644 "$partial"
  mv "$partial" "$destination"
  echo "Downloaded and verified $name"
}
# Pin the complete published checksum file as well as each relevant artifact.
fetch sha256sum-amd64.txt "$RELEASE/sha256sum-amd64.txt" '2529ab5abe30b2d2db1e2f8018a67e75eb443381145316469538092d9958fbfd'
python3 - "$PACKAGES/sha256sum-amd64.txt" <<'PY-CHECKSUM'
from pathlib import Path
import sys
checks = {parts[-1].lstrip('*'): parts[0] for line in Path(sys.argv[1]).read_text().splitlines()
          if len(parts := line.split()) == 2}
expected = {
    'k3s': 'ef1df26b26276c0f6d962391c94e12f9362d1f1e30ec7a7926e9ddb84b0d66ce',
    'k3s-airgap-images-amd64.tar.zst': 'c2c6571bee0e2cee5cc3e248aa0edc0343bcbfc0e512589630030b635be3d581',
}
if any(checks.get(name) != digest for name, digest in expected.items()):
    raise SystemExit('Pinned release checksum entries do not match.')
PY-CHECKSUM
fetch k3s "$RELEASE/k3s" 'ef1df26b26276c0f6d962391c94e12f9362d1f1e30ec7a7926e9ddb84b0d66ce'
chmod 755 "$PACKAGES/k3s"
fetch install.sh "https://raw.githubusercontent.com/k3s-io/k3s/${VERSION//+/%2B}/install.sh" '40b487f0d8ef4f5d1bf422e7bb6228cc7789c40ecc66c5ab067d396bbee9816e'
fetch k3s-airgap-images-amd64.tar.zst "$RELEASE/k3s-airgap-images-amd64.tar.zst" 'c2c6571bee0e2cee5cc3e248aa0edc0343bcbfc0e512589630030b635be3d581'
if [ "$MODE" = download ]; then
  echo "Native K3s packages are ready; no system services were changed."
  exit 0
fi
# The project config and marker are checked before writing any host integration.
STATE=$(python3 - "$CONFIG" <<'PY-PREFLIGHT'
from pathlib import Path
import hashlib, json, re, subprocess, sys, yaml
cfg = Path(sys.argv[1])
config = cfg/'k3s.yaml'
marker = cfg/'native-installation.json'
from deployment_context import load_context
ctx=load_context(); s=ctx.settings; runtime=ctx.runtime_root
cfg.mkdir(parents=True,exist_ok=True)
desired = {
    'node-name': s['host_name'].lower(), 'node-ip':s['host_ip'], 'advertise-address':s['host_ip'],
    'bind-address':'0.0.0.0','https-listen-port':s['kube_api_port'],'flannel-iface':s['interface'],
    'cluster-cidr':s['pod_cidr'],'service-cidr':s['service_cidr'],
    'data-dir':str(runtime/'dps-install/data/kubernetes/k3s'),
    'default-local-storage-path':str(runtime/'dps-install/data/kubernetes/storage'),
    'kubelet-arg':['root-dir='+str(runtime/'dps-install/data/kubernetes/kubelet')],
    'resolv-conf':s['resolv_conf'],'write-kubeconfig':str(cfg/'k3s-admin.yaml'),
    'write-kubeconfig-mode':'0600','tls-san':[s['host_ip'],s['host_name'],s['host_name'].lower()],
}
if config.is_symlink() or (config.exists() and not config.is_file()):
    raise SystemExit('Unexpected native configuration target; preserve it and stop.')
if config.exists():
    # Preserve original bytes/inode and marker hash when formatting differs only.
    if yaml.safe_load(config.read_text()) != desired:
        raise SystemExit('Native configuration conflicts with deployment.yaml; review before changing the service.')
else:
    config.write_text(yaml.safe_dump(desired,sort_keys=False));config.chmod(0o600)
digest = hashlib.sha256(config.read_bytes()).hexdigest()
binary = Path('/usr/local/bin/k3s')
unit = Path('/etc/systemd/system/k3s.service')
envfile = Path('/etc/systemd/system/k3s.service.env')
dropin = Path('/etc/systemd/system/k3s.service.d/deploy-mount.conf')
existing = any(p.exists() or p.is_symlink() for p in [binary,unit,envfile,dropin])
owned = None
if marker.exists():
    owned = json.loads(marker.read_text())
    if owned.get('config_sha256') != digest or owned.get('version') != s['k3s_version']:
        raise SystemExit('Existing native installation marker conflicts with this configuration.')
if existing and owned is None:
    raise SystemExit('An unrecorded system K3s installation exists. Preserve it and stop.')
if binary.exists() or binary.is_symlink():
    if binary.is_symlink() or not binary.is_file():
        raise SystemExit('The existing system K3s binary is not the expected regular file.')
    if hashlib.sha256(binary.read_bytes()).hexdigest() != 'ef1df26b26276c0f6d962391c94e12f9362d1f1e30ec7a7926e9ddb84b0d66ce':
        raise SystemExit('Existing system K3s binary has a different checksum.')
if unit.exists() or unit.is_symlink():
    if unit.is_symlink() or not unit.is_file():
        raise SystemExit('The system K3s unit must be a real regular file.')
    text = re.sub(r'\\\n[ \t]*', ' ', unit.read_text())
    start = next((line.partition('=')[2] for line in text.splitlines() if line.startswith('ExecStart=')), '')
    import shlex
    if shlex.split(start) != ['/usr/local/bin/k3s','server','--config',str(config)]:
        raise SystemExit('The existing K3s service launch configuration conflicts.')
    if envfile.exists() and any(line.strip() and not line.lstrip().startswith('#')
                                for line in envfile.read_text().splitlines()):
        raise SystemExit('Existing K3s environment overrides require explicit review.')
    for extra in Path('/etc/systemd/system/k3s.service.d').glob('*.conf'):
        if extra != dropin:
            raise SystemExit('An unrelated K3s systemd override exists; preserve it and stop.')
    if dropin.exists() and dropin.read_text() != '[Unit]\nRequiresMountsFor='+str(runtime)+'\n':
        raise SystemExit('The existing mount dependency override conflicts.')
    if subprocess.run(['systemctl','is-active','--quiet','k3s']).returncode == 0:
        print('reuse'); raise SystemExit(0)
# Before a new install, preserve any existing listener on required TCP ports.
listeners = subprocess.check_output(
    ['ss','-H','-ltn',f'( sport = :80 or sport = :443 or sport = :{s["kube_api_port"]} or sport = :6444 or sport = :10250 or sport = :10010 )'],
    text=True).strip()
if listeners:
    raise SystemExit('One or more native K3s/Ingress ports are in use; preserve the existing listener.')
print('install')
PY-PREFLIGHT
)
wait_native_node() {
  local remaining=180
  until kubectl --kubeconfig "$CONFIG/kubeconfig.yaml" --request-timeout=5s get "node/$DPS_KUBE_NODE" >/dev/null 2>&1; do
    [ "$remaining" -gt 0 ] || { echo 'Physical node $DPS_KUBE_NODE did not register within timeout.' >&2; return 1; }
    sleep 2
    remaining=$((remaining - 2))
  done
  kubectl --kubeconfig "$CONFIG/kubeconfig.yaml" wait --for=condition=Ready "node/$DPS_KUBE_NODE" --timeout=180s
}
if [ "$STATE" = reuse ]; then
  [ -f "$CONFIG/kubeconfig.yaml" ] || {
    echo "Existing service is active; run refresh-kubeconfig.py to refresh the project admin config." >&2
    exit 1
  }
  python3 "$DPS_SOURCE_ROOT/dps-install/scripts/refresh-kubeconfig.py"
  wait_native_node
  echo "The matching native K3s service is already active; reused without service changes."
  exit 0
fi
mkdir -p "$BASE/dps-install/data/kubernetes/k3s/agent/images" \
  "$BASE/dps-install/data/kubernetes/storage" \
  "$BASE/dps-install/data/kubernetes/kubelet" "$CONFIG/systemd"
chmod 700 "$BASE/dps-install/data/kubernetes/k3s" "$BASE/dps-install/data/kubernetes/kubelet"
# Image bundles stay in packages; K3s imports this read-only symlink on first start.
ln -s "$PACKAGES/k3s-airgap-images-amd64.tar.zst" \
  "$BASE/dps-install/data/kubernetes/k3s/agent/images/k3s-airgap-images-amd64.tar.zst" 2>/dev/null || \
  test "$(readlink "$BASE/dps-install/data/kubernetes/k3s/agent/images/k3s-airgap-images-amd64.tar.zst")" = "$PACKAGES/k3s-airgap-images-amd64.tar.zst"
install -m 755 "$PACKAGES/k3s" /usr/local/bin/k3s
mkdir -p /etc/systemd/system/k3s.service.d
printf '[Unit]\nRequiresMountsFor=%s\n' "$DPS_RUNTIME_ROOT" > /etc/systemd/system/k3s.service.d/deploy-mount.conf
chmod 644 /etc/systemd/system/k3s.service.d/deploy-mount.conf
cp /etc/systemd/system/k3s.service.d/deploy-mount.conf "$CONFIG/systemd/deploy-mount.conf"
python3 - "$CONFIG" <<'PY-MARKER'
from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib, json, sys
cfg = Path(sys.argv[1])
from deployment_context import load_context
s=load_context().settings
record = {
    'version': s['k3s_version'],
    'config_sha256': hashlib.sha256((cfg/'k3s.yaml').read_bytes()).hexdigest(),
    'node_name': s['host_name'].lower(),
    'api_endpoint': f"https://{s['host_ip']}:{s['kube_api_port']}",
    'binary': '/usr/local/bin/k3s',
    'systemd_unit': '/etc/systemd/system/k3s.service',
    'installation_started_at': datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
}
(cfg/'native-installation.json').write_text(json.dumps(record,indent=2)+'\n')
PY-MARKER
# Run the fixed official installer in a clean environment, using the verified binary.
# The actual unit/binary live in standard OS paths so boot does not need /raid to load the unit.
env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  INSTALL_K3S_SKIP_DOWNLOAD=true INSTALL_K3S_SYMLINK=skip \
  INSTALL_K3S_EXEC="server --config $CONFIG/k3s.yaml" \
  sh "$PACKAGES/install.sh"
[ ! -L /etc/systemd/system/k3s.service ] || {
  echo "Unexpected symlink for the standard system unit." >&2; exit 1;
}
cp /etc/systemd/system/k3s.service "$CONFIG/systemd/k3s.service"
cp /etc/systemd/system/k3s.service.env "$CONFIG/systemd/k3s.service.env"
chmod 644 "$CONFIG/systemd/k3s.service" "$CONFIG/systemd/deploy-mount.conf"
chmod 600 "$CONFIG/systemd/k3s.service.env"
python3 "$DPS_SOURCE_ROOT/dps-install/scripts/refresh-kubeconfig.py"
wait_native_node
echo "Native K3s is running on physical node $DPS_KUBE_NODE."
