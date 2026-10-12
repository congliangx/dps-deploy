#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
for arg in "$@"; do
  if [[ "$arg" == --help || "$arg" == -h ]]; then exec python3 "$script_dir/install-from-zero.py" "$@"; fi
done
bash "$script_dir/install-host-dependencies.sh"
exec python3 "$script_dir/install-from-zero.py" "$@"
