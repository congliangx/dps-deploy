#!/usr/bin/env bash
set -euo pipefail
for dps_arg in "$@"; do
  if [[ "$dps_arg" == --help || "$dps_arg" == -h ]]; then
    printf '%s\n' 'Usage: kubernetes.sh [deployment options] [status|start|stop]'
    exit 0
  fi
done
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
[[ $# -le 1 ]] || { printf '%s\n' 'Unexpected arguments; use --help.' >&2; exit 2; }
cd "$DPS_RUNTIME_ROOT"
case "${1:-status}" in
 status)
  systemctl show k3s --property=ActiveState,SubState,MainPID,FragmentPath --no-pager
  kubectl --context "$DPS_KUBE_CONTEXT" --request-timeout=10s get nodes -o wide
  kubectl --context "$DPS_KUBE_CONTEXT" --request-timeout=10s -n kube-system get pods
  ;;
 start)
  systemctl start k3s
  python3 "$DPS_SOURCE_ROOT/dps-install/scripts/refresh-kubeconfig.py"
  kubectl --context "$DPS_KUBE_CONTEXT" wait --for=condition=Ready node "$DPS_KUBE_NODE" --timeout=180s
  ;;
 stop) systemctl stop k3s ;;
 *) echo 'Usage: kubernetes.sh status|start|stop' >&2; exit 2 ;;
esac
