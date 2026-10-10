#!/usr/bin/env bash
set -euo pipefail
cd /raid/vince/deploy
dpsctl_image=nvcr.io/nvidia/dpsctl@sha256:27fa8297f0efc18a0d22a6822c812347a7706bb2fc19f4d5c901f7125361bfdb
dpsctl_target=/raid/vince/deploy/dps-install/packages/tools/bin/dpsctl
check_dpsctl_paths() {
  [[ ! -L "$dpsctl_target" ]] || { echo 'Project dpsctl is a symbolic link; preserve it and stop.' >&2; exit 1; }
  [[ ! -e "$dpsctl_target" || -f "$dpsctl_target" ]] || { echo 'Project dpsctl is not a regular file; stop.' >&2; exit 1; }
  if [[ -e /usr/local/bin/dpsctl || -L /usr/local/bin/dpsctl ]]; then
    [[ -L /usr/local/bin/dpsctl && $(readlink -f /usr/local/bin/dpsctl) == "$dpsctl_target" ]] || { echo 'Existing unrelated dpsctl binary; preserve it and stop.' >&2; exit 1; }
  fi
}
check_dpsctl_paths
mkdir -p /raid/vince/deploy/dps-install/packages/tools/bin
dpsctl_stage=$(mktemp -d /raid/vince/deploy/dps-install/packages/tools/.dpsctl-stage.XXXXXX)
dpsctl_container_id=''
cleanup_dpsctl() {
  if [[ -n "$dpsctl_container_id" ]]; then
    docker rm "$dpsctl_container_id" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$dpsctl_stage"
}
trap cleanup_dpsctl EXIT
docker image inspect "$dpsctl_image" >/dev/null 2>&1 || docker pull "$dpsctl_image"
dpsctl_container_id=$(docker create "$dpsctl_image")
docker cp "$dpsctl_container_id":/dpsctl "$dpsctl_stage/dpsctl"
chmod 755 "$dpsctl_stage/dpsctl"
dpsctl_actual=$("$dpsctl_stage/dpsctl" --version)
[[ $(printf '%s\n' "$dpsctl_actual" | awk '/^Version:/ {print $2}') == 0.9.0 ]] || { echo 'dpsctl version mismatch; existing binary is unchanged.' >&2; exit 1; }
check_dpsctl_paths
mv -T -- "$dpsctl_stage/dpsctl" "$dpsctl_target"
if [[ ! -L /usr/local/bin/dpsctl ]]; then
  ln -s "$dpsctl_target" /usr/local/bin/dpsctl
fi
"$dpsctl_target" --version
