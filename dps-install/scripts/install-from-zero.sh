#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Help is safe even before Python/PyYAML are installed or deployment.yaml exists.
for arg in "$@"; do
  if [[ "$arg" == --help || "$arg" == -h ]]; then
    printf '%s\n' \
      'Usage: bash install-from-zero.sh [deployment overrides] [--kubeconfig FILE]' \
      '       [--download-only | --prepare-only]' \
      'Install the complete Lab, or stop after artifact download/configuration.' \
      'Common overrides: --config FILE, --runtime-root DIR, --host-ip IP,' \
      '  --namespace NAME, --release NAME, --instance-prefix NAME.' \
      'Run python3 dps-install/scripts/install-from-zero.py --help for all overrides.'
    exit 0
  fi
done
# Validate flags/values without Python so even a bare OS cannot mutate on a typo.
validate_args=("$@")
mode=''
while [[ $# -gt 0 ]]; do
  flag=$1
  case "$flag" in
    --download-only|--prepare-only)
      [[ -z "$mode" || "$mode" == "$flag" ]] || {
        echo '--download-only and --prepare-only are mutually exclusive.' >&2; exit 2;
      }
      mode=$flag; shift; continue ;;
  esac
  case "$flag" in
    *=*) value=${flag#*=}; flag=${flag%%=*}; shift ;;
    *)
      [[ $# -ge 2 && "$2" != -* ]] || { echo "Missing value for $flag." >&2; exit 2; }
      value=$2; shift 2 ;;
  esac
  case "$flag" in
    --source-root|--root|--runtime-root|--deployment-config|--config|--host-ip|--host-name|--interface|--namespace|--release|--agent-id|--api-name|--ui-name|--instance-prefix|--pg-subnet|--pod-cidr|--service-cidr|--kube-context|--topology-name|--pg-project|--ldap-project|--bmc-project|--k3s-version|--helm-version|--kubectl-version|--dps-version|--kubeconfig)
      [[ -n "$value" ]] || { echo "Empty value for $flag." >&2; exit 2; } ;;
    --pg-port|--ldap-port|--bmc-start-port|--kube-api-port)
      [[ "$value" =~ ^\+?[0-9]+$ ]] || { echo "Invalid integer port for $flag." >&2; exit 2; }
      digits=${value#+}
      while [[ "$digits" == 0* && ${#digits} -gt 1 ]]; do digits=${digits#0}; done
      maximum=65535
      [[ "$flag" != --bmc-start-port ]] || maximum=65464
      [[ ${#digits} -le 5 ]] && (( 10#$digits >= 1 && 10#$digits <= maximum )) || {
        echo "Port for $flag must be in 1..$maximum." >&2; exit 2;
      } ;;
    *) echo "Unknown installation option: $flag; use --help." >&2; exit 2 ;;
  esac
done
set -- "${validate_args[@]}"
if command -v python3 >/dev/null 2>&1; then
  python3 "$script_dir/install-from-zero.py" --validate-only "$@"
fi
bash "$script_dir/install-host-dependencies.sh"
# The host bootstrap installs Python on a bare OS; repeat the stdlib-only check.
python3 "$script_dir/install-from-zero.py" --validate-only "$@"
exec python3 "$script_dir/install-from-zero.py" "$@"
