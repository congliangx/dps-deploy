#!/usr/bin/env bash
set -euo pipefail
for dps_arg in "$@"; do
  if [[ "$dps_arg" == --help || "$dps_arg" == -h ]]; then
    printf '%s\n' 'Usage: verify-simulator.sh [deployment options] [--control]'
    exit 0
  fi
done
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/../../dps-install/scripts/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --control ) ]]; then
  echo 'Usage: verify-simulator.sh [deployment options] [--control]' >&2
  exit 2
fi
mkdir -p "$DPS_RUNTIME_ROOT/verification/logs"
python3 "$script_dir/verify-bmc-inventory.py" | tee "$DPS_RUNTIME_ROOT/verification/logs/verify-bmc-inventory.log"
if [[ ${1:-} == --control ]]; then
  python3 "$script_dir/verify-bmc.py" --control | tee "$DPS_RUNTIME_ROOT/verification/logs/verify-bmc-control.log"
fi
