#!/usr/bin/env python3
"""Freeze and import PRS images into native K3s from locally verified Docker archives."""
import hashlib,json,os,subprocess
from pathlib import Path
B=Path('/raid/vince/deploy');P=B/'dps-install/config/prs';PKG=B/'dps-install/packages/prs'
os.umask(0o077);PKG.mkdir(parents=True,exist_ok=True)
tags=['nvcr.io/nvidia/power-config:2.1.0','nvcr.io/nvidia/power-controller:2.1.0','busybox:1.37-glibc','chrislusf/seaweedfs:4.18','otel/opentelemetry-collector-contrib:0.110.0']
manifest=P/'runtime-images.json'
old=json.loads(manifest.read_text()) if manifest.exists() else None
records=[]
for tag in tags:
 x=json.loads(subprocess.check_output(['docker','image','inspect',tag],text=True))[0]
 row={'tag':tag,'digest':x['RepoDigests'][0],'image_id':x['Id']}
 if old:
  previous=next(i for i in old['images']if i['tag']==tag)
  assert row==previous,'PRS image identity changed: '+tag
 records.append(row)
archive=PKG/'prs-2.1.0-runtime.tar'
if not archive.exists():
 subprocess.run(['docker','save','--output',str(archive)+'.tmp',*tags],check=True)
 Path(str(archive)+'.tmp').replace(archive)
h=hashlib.sha256()
with archive.open('rb')as f:
 for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
if old:assert old['archive_sha256']==h.hexdigest(),'PRS runtime archive checksum changed'
value={'images':records,'archive':str(archive),'archive_sha256':h.hexdigest()}
manifest.write_text(json.dumps(value,indent=2)+'\n');manifest.chmod(0o600)
subprocess.run(['k3s','ctr','-n','k8s.io','images','import',str(archive)],check=True,stdout=subprocess.DEVNULL)
print(json.dumps({'imported_images':len(records),'archive':str(archive),'archive_sha256':h.hexdigest()}))
