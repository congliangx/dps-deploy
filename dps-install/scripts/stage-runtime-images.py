#!/usr/bin/env python3
"""Stage pinned DPS images into native K3s containerd without deploying workloads."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
from deployment_context import context_from_cli
ctx = context_from_cli()
import json,subprocess,os
B=ctx.runtime_root;P=B/'dps-install/packages/images';P.mkdir(parents=True,exist_ok=True)
def run(*args):subprocess.run(args,check=True)
def image_id(name):
 p=subprocess.run(['docker','image','inspect',name,'--format','{{.Id}}'],capture_output=True,text=True)
 return p.stdout.strip() if p.returncode==0 else None
run('systemctl','is-active','--quiet','k3s')
images=json.loads(ctx.source_path('dps-install/config/runtime-images.json').read_text())
for item in images:
 if not image_id(item['digest']):run('docker','pull',item['digest'])
 tag_id=image_id(item['name']);target_id=image_id(item['digest'])
 if tag_id and tag_id!=target_id:raise RuntimeError('Existing image tag differs: '+item['name']+'; review before changing.')
 run('docker','tag',item['digest'],item['name'])
archive=P/'dps-0.9.0-runtime.tar';stage=P/'.dps-0.9.0-runtime.tar.tmp'
try:
 run('docker','save','--output',str(stage),*[i['name'] for i in images]);stage.chmod(0o600);os.replace(stage,archive)
 run('/usr/local/bin/k3s','ctr','--namespace','k8s.io','images','import',str(archive))
finally:
 if stage.exists():stage.unlink()
print('Pinned DPS Core/Agent/UI 0.9.0 images staged in native containerd; no Helm install performed.')
