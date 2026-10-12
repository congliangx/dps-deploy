#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "$BASH_SOURCE")" && pwd)
exec python3 "$script_dir/../../dps-install/scripts/install-component.py" --component bmc "$@"
