#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ${1:-} != --help && ${1:-} != -h ]]; then
  bash "$script_dir/install-host-dependencies.sh"
fi
exec python3 "$script_dir/install-from-zero.py" "$@"
