#!/usr/bin/env python3
"""Configure 72 BMC HTTPS entrypoints, preserving SDK Host based device state."""
import csv, json, re, socket
from pathlib import Path
import yaml
BASE=Path('/raid/vince/deploy')
SIM=BASE/'hardware-sim/runtime'
DPS_CONFIG=BASE/'dps-install/config'
nodes=json.loads((SIM/'nodes.json').read_text())
assert len(nodes)==72 and len({n['node_id'] for n in nodes})==72
lines=['worker_processes 2;','error_log /dev/stderr warn;','pid /var/run/nginx.pid;','events { worker_connections 4096; }','http {','  access_log /dev/stdout;','  upstream gb300_backend { server simulator:8443; keepalive 256; }','  ssl_certificate /etc/bmc-tls/tls.crt;','  ssl_certificate_key /etc/bmc-tls/tls.key;','  ssl_protocols TLSv1.2 TLSv1.3;']
for n in nodes:
 assert re.fullmatch(r'gb300-r0[1-4]-00(?:0[1-9]|1[0-8])',n['node_id'])
 lines += ['  server {',f"    listen {n['port']} ssl;",f"    server_name {n['node_id']};",'    location / {','      proxy_pass https://gb300_backend;',f"      proxy_set_header Host {n['node_id']};",f"      proxy_set_header X-Forwarded-Host {n['node_id']};",'      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;','      proxy_set_header Connection "";','      proxy_http_version 1.1;','      proxy_ssl_verify off;','      proxy_buffering off;','      proxy_redirect off;','      proxy_read_timeout 60s;','    }','  }']
lines.append('}')
(SIM/'nginx.conf').write_text('\n'.join(lines)+'\n')
c=yaml.safe_load((SIM/'compose.yaml').read_text())
c['services']['proxy']={'image':'nginx@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236','container_name':'dps-gb300-bmc-proxy','restart':'unless-stopped','entrypoint':['nginx','-g','daemon off;'],'depends_on':['simulator'],'volumes':['./nginx.conf:/etc/nginx/nginx.conf:ro','./tls:/etc/bmc-tls:ro'],'ports':['10.6.131.43:18443-18514:18443-18514'],'networks':['bmc'],'cpus':2,'mem_limit':'512m','healthcheck':{'test':['CMD','wget','-q','--no-check-certificate','-O','/dev/null','https://127.0.0.1:18443/readyz'],'interval':'15s','timeout':'5s','retries':3},'logging':{'driver':'json-file','options':{'max-size':'20m','max-file':'3'}}}
(SIM/'compose.yaml').write_text(yaml.safe_dump(c,sort_keys=False))
text=(BASE/'hardware-sim/vendor/dps-bmc-simulator/templates/secrets/bmc-gb300-simulator.yaml').read_text()
cred={k:re.search(r'"'+k+r'":\s*"([^"]+)"',text).group(1) for k in ('username','password')}
for filename,content in [('bmc-credentials.json',json.dumps(cred,indent=2)+'\n'),('bmc-shared-secret.yaml',yaml.safe_dump({'apiVersion':'v1','kind':'Secret','metadata':{'name':'bmc-shared-secret'},'type':'Opaque','stringData':{'bmc':json.dumps(cred)}},sort_keys=False))]:
 p=DPS_CONFIG/filename
 p.touch(mode=0o600,exist_ok=True);p.chmod(0o600);p.write_text(content)
p=DPS_CONFIG/'bmc-endpoints.csv';p.touch(mode=0o600,exist_ok=True);p.chmod(0o600)
with p.open('w',newline='') as f:
 fields=['rack_id','node_id','bmc_url','redfish_system_url','username','password']
 writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
 for n in nodes:
  writer.writerow({k:val for k,val in dict(rack_id=n['rack_id'],node_id=n['node_id'],bmc_url=n['bmc_url'],redfish_system_url=n['bmc_url']+'/redfish/v1/Systems/HGX_Baseboard_0',**cred).items()})
print('Configured 72 distinct HTTPS routes and credential files (mode 600).')
