#!/usr/bin/env bash
set -euo pipefail
ROOT=/raid/vince/deploy
# Fixed official Debian base + downloaded authenticated Debian package files.
cd "$ROOT/dps-install/packages/ldap/build"
sha256sum --check SHA256SUMS
docker build --network=none -t dps-openldap:2.6.10-debian13 .
actual=$(docker image inspect --format '{{.Id}}' dps-openldap:2.6.10-debian13)
echo "Built runtime image: $actual"
echo 'If a rebuild changes the image identity, review and update the fixed deployment manifest before use.'
