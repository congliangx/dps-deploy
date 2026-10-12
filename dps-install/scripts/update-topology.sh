#!/usr/bin/env bash
# Update an existing inactive topology with the server's current optimistic-lock hash.
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deployment-env.sh" "$@"
set -- "${DPS_DEPLOY_ARGS[@]}"
umask 077
base=$DPS_RUNTIME_ROOT
export DPSCTL_CREDENTIALS_PATH="${DPSCTL_CREDENTIALS_PATH:-$base/dps-install/config/dpsctl/credentials.yaml}"
export DPSCTL_LOG_FILE="${DPSCTL_LOG_FILE:-$base/verification/logs/dpsctl.log}"
[[ $# -eq 0 ]] || { printf '%s\n' 'Usage: update-topology.sh' >&2; exit 2; }
[[ -s "$DPSCTL_CREDENTIALS_PATH" ]] || { printf '%s\n' 'Authenticate using the project dpsctl credentials path first.' >&2; exit 1; }
"$DPS_SOURCE_ROOT/dps-install/scripts/register-devices.sh"
python3 - "$base/dps-install/config/topology-4rack-dps09.json" <<'PYTHON'
import base64,copy,json,os,pathlib,subprocess,sys,urllib.request,urllib.error,yaml
input_path=pathlib.Path(sys.argv[1])
desired=json.loads(input_path.read_text())
name=desired['Topology']['Name']
if name!=os.environ['DPS_TOPOLOGY_NAME'] or desired.get('Policies'):
 raise SystemExit('Unexpected topology name or legacy policies in input')
compute={e['Name'] for e in desired['Entities'] if e.get('Type')=='ComputerSystem'}
routed={e['Name'] for e in desired['Topology']['Entities'] if e.get('AgentId')==os.environ['DPS_AGENT_ID']}
if len(compute)!=72 or routed!=compute:
 raise SystemExit('All 72 compute relationship objects must route to the configured agent')
if 'topologyHash' in desired or 'topologyHash' in desired['Topology']:
 raise SystemExit('Stable installation input must not contain a stale runtime topology hash')
def cli(args):
 r=subprocess.run(['dpsctl','--output','json',*args],capture_output=True,text=True)
 if r.returncode:
  # dpsctl may encode application errors in stdout; do not log any credential file.
  if r.stdout: print(r.stdout)
  if r.stderr: print(r.stderr,file=sys.stderr)
  raise SystemExit(r.returncode)
 x=json.loads(r.stdout)
 return x
def inactive():
 x=cli(['topology','list'])
 rows=[t for t in x.get('topologies',[]) if t.get('topology_name')==name]
 if x.get('status',{}).get('ok') is not True or len(rows)!=1 or rows[0].get('is_active',False):
  raise SystemExit('Existing target topology must be inactive; no lifecycle changes were made')
 return rows[0]
inactive()
validation=cli(['topology','validate',str(input_path)])
print(json.dumps(validation))
if validation.get('status',{}).get('ok') is not True:
 raise SystemExit('Topology semantic validation failed')
# CLI export sanitizes away topologyHash; read the actual GetTopologyModel header.
# Core's internal HTTP gateway is the existing UI backend and is not published externally.
credentials=yaml.safe_load(pathlib.Path(os.environ['DPSCTL_CREDENTIALS_PATH']).read_text())
token=credentials.get('token',{}).get('access_token')
if not token: raise SystemExit('No DPS access token in the protected project credentials file')
svc=json.loads(subprocess.run(['kubectl','--context',os.environ['DPS_KUBE_CONTEXT'],'-n',os.environ['DPS_NAMESPACE'],'get','service',os.environ['DPS_FULLNAME']+'-server-http','-o','json'],capture_output=True,text=True,check=True).stdout)
ip=svc['spec']['clusterIP']
port=next(p['port'] for p in svc['spec']['ports'] if p['name']=='dps-http')
url=f'http://{ip}:{port}/nvidia.dcpower.v1.TopologyManagementService/GetTopologyModel'
req=urllib.request.Request(url,data=json.dumps({'topology_name':name}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token},method='POST')
with urllib.request.urlopen(req,timeout=45) as response:
 rows=[json.loads(line) for line in response.read().decode().splitlines() if line.strip()]
headers=[r.get('result',{}).get('header') for r in rows if r.get('result',{}).get('header')]
if len(headers)!=1 or headers[0].get('topologyName')!=name:
 raise SystemExit('GetTopologyModel did not return the expected unique topology header')
current_hash=headers[0].get('topologyHash')
if not current_hash or len(base64.b64decode(current_hash,validate=True))!=32:
 raise SystemExit('GetTopologyModel did not return a valid SHA256 topology hash')
def normalize_relation(entity,children):
 # Ignore computed timestamps; compare every other metadata/limit/property field.
 record=copy.deepcopy(entity)
 for key in ('UpdatedAt','CreatedAt'): record.pop(key,None)
 record.setdefault('AgentId','')
 record.setdefault('FeedTag','')
 if record.get('Properties') is None: record['Properties']={}
 if isinstance(record.get('OperatingLimit'),dict):
  record['OperatingLimit'].setdefault('PowerFactor',0)
 record['Children']=sorted(children)
 return record
def desired_relations():
 return {e['Name']:normalize_relation({k:v for k,v in e.items() if k!='Children'},e.get('Children',[])) for e in desired['Topology']['Entities']}
def raw_relations(model_rows):
 entities=[e for row in model_rows for e in row.get('result',{}).get('entities',[])]
 return {e['entity']['Name']:normalize_relation(e['entity'],e.get('children',[])) for e in entities}
# Use the explicit official update RPC: observed CLI update reached CREATE and
# failed on the existing topology name. Do not delete/reimport or use --force.
# Omit policyBundle so the existing topology selection remains unchanged.
if raw_relations(rows)==desired_relations():
 print('Stored topology already has all desired relation fields, limits/properties, and 72 agent routes; no topology write performed.')
else:
 inactive()
 relation_messages=[]
 for relation in desired['Topology']['Entities']:
  relation_messages.append({'entity':{k:v for k,v in relation.items() if k!='Children'},'children':relation.get('Children',[])})
 operation={'updateTopology':{'topologyName':name,'topologyHash':current_hash,'forceUpdate':False}}
 if headers[0].get('properties') is not None:
  operation['updateTopology']['properties']=headers[0]['properties']
 messages=[operation,{'entities':relation_messages}]
 assert 'createTopology' not in operation and 'policyBundle' not in operation['updateTopology']
 request_body=('\n'.join(json.dumps(m,separators=(',',':')) for m in messages)+'\n').encode()
 update_url=f'http://{ip}:{port}/nvidia.dcpower.v1.TopologyManagementService/CreateUpdateTopology'
 req=urllib.request.Request(update_url,data=request_body,headers={'Content-Type':'application/json','Authorization':'Bearer '+token},method='POST')
 try:
  with urllib.request.urlopen(req,timeout=60) as response:
   result=json.loads(response.read())
 except urllib.error.HTTPError as error:
  print('Explicit inactive topology API update returned HTTP',error.code)
  print(error.read().decode()[:2000])
  raise SystemExit(1)
 if 'result' in result: result=result['result']
 print(json.dumps(result))
 if result.get('status',{}).get('ok') is not True:
  raise SystemExit('Explicit API update did not return status.ok=true')
# The CLI export omits routing AgentId in this artifact. Verify the actual raw
# GetTopologyModel entity Structs instead of inferring persistence from export.
req=urllib.request.Request(url,data=json.dumps({'topology_name':name}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token},method='POST')
with urllib.request.urlopen(req,timeout=45) as response:
 stored_rows=[json.loads(line) for line in response.read().decode().splitlines() if line.strip()]
if raw_relations(stored_rows)!=desired_relations():
 raise SystemExit('Stored topology relation metadata, limits/properties, or 72 agent routes differ from desired input')
exported=cli(['topology','export','--topology',name])
for inventory_name,e in {e['Name']:e for e in exported['Entities']}.items():
 original=next((x for x in desired['Entities'] if x['Name']==inventory_name),None)
 if original is None or any(e.get(k)!=original.get(k) for k in ['Name','Type','Model','Redfish']):
  raise SystemExit('Stored inventory identity or Redfish endpoint differs from desired input')
final=inactive()
if final.get('policy_bundle','')!=headers[0].get('policyBundle',''): raise SystemExit('Stored policy bundle changed unexpectedly')
print('PASS: 72 stored AgentId routes, original inventory/Children preserved, topology remains inactive; no persistent runtime-hash input generated.')
PYTHON
