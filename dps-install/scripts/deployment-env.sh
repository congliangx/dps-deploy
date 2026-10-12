#!/usr/bin/env bash
# Source this file, then set -- "${DPS_DEPLOY_ARGS[@]}" to retain command-specific args.
dps_context_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DPS_DEPLOY_ARGS=()
dps_context_options=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-root=*|--root=*|--runtime-root=*|--deployment-config=*|--config=*|--host-ip=*|--host-name=*|--interface=*|--namespace=*|--release=*|--agent-id=*|--api-name=*|--ui-name=*|--instance-prefix=*|--pg-port=*|--ldap-port=*|--bmc-start-port=*|--pg-subnet=*|--pod-cidr=*|--service-cidr=*|--kube-api-port=*|--kube-context=*|--topology-name=*|--pg-project=*|--ldap-project=*|--bmc-project=*|--k3s-version=*|--helm-version=*|--kubectl-version=*|--dps-version=*)
      dps_context_options+=("${1%%=*}" "${1#*=}"); shift ;;
    --source-root|--root|--runtime-root|--deployment-config|--config|--host-ip|--host-name|--interface|--namespace|--release|--agent-id|--api-name|--ui-name|--instance-prefix|--pg-port|--ldap-port|--bmc-start-port|--pg-subnet|--pod-cidr|--service-cidr|--kube-api-port|--kube-context|--topology-name|--pg-project|--ldap-project|--bmc-project|--k3s-version|--helm-version|--kubectl-version|--dps-version)
      [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; return 2; }
      dps_context_options+=("$1" "$2"); shift 2 ;;
    *) DPS_DEPLOY_ARGS+=("$1"); shift ;;
  esac
done
dps_context_exports=$(PYTHONDONTWRITEBYTECODE=1 python3 "$dps_context_dir/deployment_context.py" --shell "${dps_context_options[@]}") || return
# Values are produced using Python shlex.quote from public settings, never credentials.
eval "$dps_context_exports"
unset dps_context_exports dps_context_options dps_context_dir
# Native manual installs keep matching tools in runtime; each new shell needs this path.
dps_tools_dir="$DPS_RUNTIME_ROOT/dps-install/packages/tools/bin"
if [[ -d "$dps_tools_dir" ]]; then
  IFS=: read -r -a dps_path_parts <<< "${PATH:-}"
  dps_tools_path="$dps_tools_dir"
  for dps_path_part in "${dps_path_parts[@]}"; do
    [[ "$dps_path_part" == "$dps_tools_dir" ]] && continue
    dps_tools_path+=":$dps_path_part"
  done
  export PATH="$dps_tools_path"
fi
unset dps_tools_dir dps_path_parts dps_tools_path dps_path_part

# Require the configured Compose project to match an existing migrated instance.
dps_compose_project() {
  local owner
  owner=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$1" 2>/dev/null) || owner=''
  if [[ -n "$owner" && "$owner" != '<no value>' && "$owner" != "$2" ]]; then
    echo 'Existing Compose project differs from deployment.yaml; preserve it and review.' >&2; return 1
  fi
  printf '%s\n' "$2"
}
