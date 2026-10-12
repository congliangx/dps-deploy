#!/usr/bin/env python3
"""Refresh the runtime BMC proxy routes without replacing retained credentials."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'dps-install/scripts'))
from deployment_context import context_from_cli
import csv, json, os, re
import yaml
ctx = context_from_cli()
os.umask(0o077)
s = ctx.settings
sim = ctx.runtime_path('hardware-sim/runtime')
config = ctx.runtime_path('dps-install/config')
nodes_path = sim / 'nodes.json'
nodes = json.loads((nodes_path if nodes_path.exists() else ctx.source_path('hardware-sim/templates/nodes.json')).read_text())
if len(nodes) != 72 or len({n['node_id'] for n in nodes}) != 72:
    raise ValueError('Expected 72 unique GB300 nodes')
credentials = config / 'bmc-credentials.json'
if not credentials.exists():
    raise ValueError('Prepare the simulator identity first; proxy maintenance cannot generate or replace credentials')
cred = json.loads(credentials.read_text())
for index, node in enumerate(nodes):
    node['port'] = s['bmc_start_port'] + index
    node['bmc_url'] = f"https://{s['host_ip']}:{node['port']}"
lines = ['worker_processes 2;', 'error_log /dev/stderr warn;', 'pid /var/run/nginx.pid;',
         'events { worker_connections 4096; }', 'http {', 'access_log /dev/stdout;',
         'upstream gb300_backend { server simulator:8443; keepalive 256; }',
         'ssl_certificate /etc/bmc-tls/tls.crt;', 'ssl_certificate_key /etc/bmc-tls/tls.key;',
         'ssl_protocols TLSv1.2 TLSv1.3;']
for n in nodes:
    if not re.fullmatch(r'gb300-r0[1-4]-00(?:0[1-9]|1[0-8])', n['node_id']):
        raise ValueError('Unexpected node identifier')
    lines += ['server {', f"listen {n['port']} ssl;", f"server_name {n['node_id']};", 'location / {',
              'proxy_pass https://gb300_backend;', f"proxy_set_header Host {n['node_id']};",
              f"proxy_set_header X-Forwarded-Host {n['node_id']};", 'proxy_set_header Connection "";',
              'proxy_http_version 1.1;', 'proxy_ssl_verify off;', 'proxy_read_timeout 60s;', '}', '}']
lines.append('}')
sim.mkdir(parents=True, exist_ok=True)
(sim / 'nginx.conf').write_text('\n'.join(lines) + '\n')
compose = yaml.safe_load((sim / 'compose.yaml').read_text())
proxy = compose['services']['proxy']
proxy.update(container_name=s['proxy_container'],
             ports=[f"{s['host_ip']}:{s['bmc_start_port']}-{s['bmc_start_port']+71}:{s['bmc_start_port']}-{s['bmc_start_port']+71}"],
             volumes=[str(sim/'nginx.conf')+':/etc/nginx/nginx.conf:ro', str(sim/'tls')+':/etc/bmc-tls:ro'])
proxy['healthcheck']['test'] = ['CMD','wget','-q','--no-check-certificate','-O','/dev/null',
                              f"https://127.0.0.1:{s['bmc_start_port']}/readyz"]
(sim / 'compose.yaml').write_text(yaml.safe_dump(compose, sort_keys=False))
nodes_path.write_text(json.dumps(nodes, indent=2)+'\n')
secret = {'apiVersion':'v1','kind':'Secret','metadata':{'name':'bmc-shared-secret','namespace':s['namespace'],
          'labels':{'app.kubernetes.io/component':'bmc-credentials'}},'type':'Opaque','stringData':{'bmc':json.dumps(cred)}}
target = config / 'bmc-shared-secret.yaml'
target.write_text(yaml.safe_dump(secret,sort_keys=False));target.chmod(0o600)
with (config/'bmc-endpoints.csv').open('w',newline='') as f:
    fields=['rack_id','node_id','bmc_url','redfish_system_url','username','password']
    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
    for n in nodes:
        writer.writerow({**{k:n[k] for k in fields[:3]},
                         'redfish_system_url':n['bmc_url']+'/redfish/v1/Systems/HGX_Baseboard_0',**cred})
(config/'bmc-endpoints.csv').chmod(0o600)
print('Updated 72 runtime proxy routes; retained the existing BMC identity.')
