#!/usr/bin/env python3
"""Verify actual SDK Redfish interfaces, and restore every changed GPU limit."""

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
import base64, concurrent.futures, json, ssl, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path
BASE=CTX.runtime_root
nodes=json.loads((BASE/'hardware-sim/runtime/nodes.json').read_text())
creds=json.loads((BASE/'dps-install/config/bmc-credentials.json').read_text())
context=ssl._create_unverified_context()
header='Basic '+base64.b64encode((creds['username']+':'+creds['password']).encode()).decode()
PATH='/redfish/v1/Systems/HGX_Baseboard_0/Processors/GPU_0/EnvironmentMetrics'
def request(node,path,method='GET',body=None,auth=header):
 h={'Accept':'application/json'}
 if auth is not None: h['Authorization']=auth
 data=None if body is None else json.dumps(body).encode()
 if data is not None:h['Content-Type']='application/json'
 req=urllib.request.Request(node['bmc_url']+path,data=data,headers=h,method=method)
 try:
  with urllib.request.urlopen(req,context=context,timeout=15) as r:
   b=r.read();d=json.loads(b) if b and b.lstrip().startswith((b'{',b'[')) else b.decode()
   return r.status,dict(r.headers),d
 except urllib.error.HTTPError as e:
  return e.code,dict(e.headers),e.read().decode()
def metric(node):
 code,_,d=request(node,PATH);assert code==200,(node['node_id'],code)
 return d['PowerLimitWatts']['SetPoint']
report={'time_utc':datetime.now(timezone.utc).isoformat(),'rack_count':4,'nodes':72,'tls':'self-signed','checks':{}}
for label,auth in [('without_auth',None),('configured_credentials',header),('wrong_credentials','Basic '+base64.b64encode(b'wrong:wrong').decode())]:
 report['checks'][label]={'http_status':request(nodes[0],'/redfish/v1/',auth=auth)[0]}
report['authentication_enforced']=report['checks']['wrong_credentials']['http_status'] in [401,403]
code,h,d=request(nodes[0],'/redfish/v1/SessionService/Sessions','POST',{'UserName':creds['username'],'Password':creds['password']})
report['checks']['session_create']={'http_status':code,'location_present':bool(h.get('Location')),'token_present':bool(h.get('X-Auth-Token'))}
if 200<=code<300 and h.get('Location'):
 from urllib.parse import urlparse
 loc=urlparse(h['Location']).path
 report['checks']['session_delete']={'http_status':request(nodes[0],loc,'DELETE')[0]}
original={n['node_id']:metric(n) for n in nodes}
modified=[];power=[];restore=[]
try:
 for i,n in enumerate(nodes):
  target=700+i*2
  modified.append(n)
  status,_,_=request(n,PATH,'PATCH',{'PowerLimitWatts':{'SetPoint':target}})
  assert status in [200,202,204],(n['node_id'],status)
  got=metric(n)
  assert got==target,(n['node_id'],target,got)
  power.append({'node_id':n['node_id'],'requested_w':target,'observed_w':got,'patch_status':status})
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
  observed=list(pool.map(metric,nodes))
 expected=[700+i*2 for i in range(len(nodes))]
 report['checks']['per_node_power_control']={'passed':len(power),'expected':72,'details':power}
 report['checks']['node_state_isolation']={'pass':observed==expected,'observed_setpoints_w':observed}
 assert observed==expected,'Node Host state isolation failed'
finally:
 for n in modified:
  status,_,_=request(n,PATH,'PATCH',{'PowerLimitWatts':{'SetPoint':original[n['node_id']]}})
  got=metric(n)
  restore.append({'node_id':n['node_id'],'http_status':status,'restored':got==original[n['node_id']]})
 report['checks']['power_restore']={'all_restored':all(r['restored'] for r in restore),'details':restore}
 (BASE/'verification/reports/verification-control.json').write_text(json.dumps(report,indent=2)+'\n')
assert all(r['restored'] for r in restore),'Power limit restoration failed'
print(json.dumps({'power_control_passed':len(power),'node_state_isolation':report['checks']['node_state_isolation']['pass'],'all_restored':report['checks']['power_restore']['all_restored'],'authentication_enforced':report['authentication_enforced'],'session_create_status':code}))
