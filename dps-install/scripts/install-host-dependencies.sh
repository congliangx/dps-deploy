#!/usr/bin/env bash
# Host bootstrap; matching existing Docker/Compose is reused without upgrading it.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Run as root.' >&2; exit 1; }
[ "$(uname -m)" = x86_64 ] || { echo 'This deployment pins amd64 artifacts.' >&2; exit 1; }
need=0
for bin in python3 openssl curl git ss jq ldapwhoami; do command -v "$bin" >/dev/null || need=1; done
python3 -c 'import yaml' >/dev/null 2>&1 || need=1
if [ "$need" = 1 ]; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-yaml openssl curl git ca-certificates iproute2 jq ldap-utils
fi
if ! command -v docker >/dev/null; then
  . /etc/os-release
  case "$ID" in ubuntu|debian) ;; *) echo 'Use Ubuntu or Debian with systemd.' >&2; exit 1;; esac
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker-bootstrap.asc
  chmod 644 /etc/apt/keyrings/docker-bootstrap.asc
  codename=${UBUNTU_CODENAME:-${VERSION_CODENAME:?}}
  architecture=$(dpkg --print-architecture)
  cat > /etc/apt/sources.list.d/docker-bootstrap.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/$ID
Suites: $codename
Components: stable
Architectures: $architecture
Signed-By: /etc/apt/keyrings/docker-bootstrap.asc
EOF
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi
docker compose version >/dev/null || { echo 'Install Docker Compose v2 matching the existing Docker installation.' >&2; exit 1; }
docker info >/dev/null
echo 'Host dependencies available; matching existing Docker services left running.'
