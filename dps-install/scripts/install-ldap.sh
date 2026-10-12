#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "$BASH_SOURCE")" && pwd)
exec python3 "$script_dir/./install-component.py" --component ldap "$@"
