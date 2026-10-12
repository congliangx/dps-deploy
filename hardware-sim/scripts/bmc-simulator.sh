#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/../../dps-install/scripts/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
bmc_action=${1:-status}
bmc_compose=(docker compose -p "$DPS_BMC_PROJECT" -f "$DPS_RUNTIME_ROOT/hardware-sim/runtime/compose.yaml")
case "$bmc_action" in
  start) "${bmc_compose[@]}" up -d ;;
  stop) "${bmc_compose[@]}" stop ;;
  restart) "${bmc_compose[@]}" restart ;;
  status) "${bmc_compose[@]}" ps ;;
  logs) "${bmc_compose[@]}" logs --tail 50 ;;
  *) echo 'Usage: bmc-simulator.sh [deployment options] start|stop|restart|status|logs' >&2; exit 2 ;;
esac
if [[ "$bmc_action" == start || "$bmc_action" == stop || "$bmc_action" == restart ]]; then
  BMC_ACTION="$bmc_action" PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
from pathlib import Path
from datetime import datetime,timezone,timedelta
import os
stamp=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
with (Path(os.environ['DPS_RUNTIME_ROOT'])/'installstep.md').open('a') as f:
    f.write(f"\n- {stamp} Successfully ran hardware-sim/scripts/bmc-simulator.sh {os.environ['BMC_ACTION']}.\n")
PY
fi
