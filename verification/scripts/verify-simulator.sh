#!/usr/bin/env bash
set -euo pipefail
cd /raid/vince/deploy
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --control ) ]]; then
  echo 'Usage: verify-simulator.sh [--control]' >&2
  exit 2
fi
python3 verification/scripts/verify-bmc-inventory.py | tee verification/logs/verify-bmc-inventory.log
if [[ ${1:-} == --control ]]; then
  python3 verification/scripts/verify-bmc.py | tee verification/logs/verify-bmc-control.log
fi
