#!/usr/bin/env python3
"""Refresh the project kubeconfig from native K3s without exposing credentials."""
from pathlib import Path
import os
import tempfile
import yaml

DIRECTORY = Path('/raid/vince/deploy/dps-install/config/kubernetes')
SOURCE = DIRECTORY / 'k3s-admin.yaml'
TARGET = DIRECTORY / 'kubeconfig.yaml'
NAME = 'dps-l20-12'
ENDPOINT = 'https://10.6.131.43:6443'

def main():
    if os.geteuid() != 0:
        raise SystemExit('Run as root on L20-12.')
    if SOURCE.is_symlink() or not SOURCE.is_file():
        raise SystemExit('Native K3s admin kubeconfig is missing or is not a regular file.')
    data = yaml.safe_load(SOURCE.read_text())
    if not isinstance(data, dict) or any(len(data.get(key, [])) != 1
                                         for key in ('clusters', 'users', 'contexts')):
        raise SystemExit('Expected a single native K3s admin context; preserve the source and stop.')
    cluster = data['clusters'][0]['cluster']
    user = data['users'][0]['user']
    if not cluster.get('certificate-authority-data') or \
       not user.get('client-certificate-data') or not user.get('client-key-data'):
        raise SystemExit('The native admin config does not contain the expected TLS credentials.')
    cluster['server'] = ENDPOINT
    data['clusters'][0]['name'] = NAME
    data['users'][0]['name'] = NAME
    data['contexts'][0]['name'] = NAME
    data['contexts'][0]['context']['cluster'] = NAME
    data['contexts'][0]['context']['user'] = NAME
    data['current-context'] = NAME
    if TARGET.is_symlink() or (TARGET.exists() and not TARGET.is_file()):
        raise SystemExit('Preserve the unexpected project kubeconfig target.')
    SOURCE.chmod(0o600)
    fd, staged = tempfile.mkstemp(prefix='.kubeconfig-', dir=DIRECTORY)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as out:
            yaml.safe_dump(data, out, sort_keys=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(staged, TARGET)
        directory_fd = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)
    print('Project kubeconfig refreshed: context dps-l20-12; endpoint https://10.6.131.43:6443; mode 600.')

if __name__ == '__main__':
    main()
