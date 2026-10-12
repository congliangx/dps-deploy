#!/usr/bin/env python3
"""Import verification-only probe images into native K3s containerd."""

# Public deployment settings select source inputs and isolated runtime outputs.
import sys as _deployment_sys
from pathlib import Path as _DeploymentPath
_deployment_sys.dont_write_bytecode = True
_deployment_sys.path.insert(0, str(_DeploymentPath(__file__).resolve().parents[2] / 'dps-install/scripts'))
from deployment_context import context_from_cli as _deployment_context
CTX = _deployment_context()
SETTINGS = CTX.settings
SOURCE_ROOT = CTX.source_root
RUNTIME_ROOT = CTX.runtime_root
for _deployment_output in ('verification/reports', 'verification/logs', 'verification/archive'):
    CTX.runtime_path(_deployment_output).mkdir(parents=True, exist_ok=True, mode=0o700)
from pathlib import Path
import subprocess,os
B=CTX.runtime_root;P=B/'verification/archive/native-k3s-migration/probe-images';P.mkdir(parents=True,exist_ok=True)
images=['postgres:17','python:3.13-slim']
for image in images:
 if subprocess.run(['docker','image','inspect',image],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:subprocess.run(['docker','pull',image],check=True)
p=P/'probe-images.tar'
try:
 subprocess.run(['docker','save','--output',str(p),*images],check=True);p.chmod(0o600)
 subprocess.run(['/usr/local/bin/k3s','ctr','--namespace','k8s.io','images','import',str(p)],check=True)
finally:
 if p.exists():p.unlink()
print('Verification-only probe images imported; temporary image archive removed.')
