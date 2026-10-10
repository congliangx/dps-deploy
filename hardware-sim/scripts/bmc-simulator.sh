#!/usr/bin/env bash
set -euo pipefail
cd /raid/vince/deploy
bmc_action=${1:-status}
bmc_compose=(docker compose -p dps-gb300-sim -f /raid/vince/deploy/hardware-sim/runtime/compose.yaml)
case "$bmc_action" in
  start) "${bmc_compose[@]}" up -d ;;
  stop) "${bmc_compose[@]}" stop ;;
  restart) "${bmc_compose[@]}" restart ;;
  status) "${bmc_compose[@]}" ps ;;
  logs) "${bmc_compose[@]}" logs --tail 50 ;;
  *) echo 'Usage: bmc-simulator.sh start|stop|restart|status|logs' >&2; exit 2 ;;
esac
if [[ "$bmc_action" == start || "$bmc_action" == stop || "$bmc_action" == restart ]]; then
  BMC_ACTION="$bmc_action" python3 - <<'PY'
from pathlib import Path
from datetime import datetime,timezone,timedelta
import os
stamp=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
with Path('installstep.md').open('a') as f:
 f.write(f"\n- {stamp} 已成功执行 `hardware-sim/scripts/bmc-simulator.sh {os.environ['BMC_ACTION']}`。\n")
PY
fi
