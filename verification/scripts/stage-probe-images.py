#!/usr/bin/env python3
"""Import verification-only probe images into native K3s containerd."""
from pathlib import Path
import subprocess,os
B=Path('/raid/vince/deploy');P=B/'verification/archive/native-k3s-migration/probe-images';P.mkdir(parents=True,exist_ok=True)
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
