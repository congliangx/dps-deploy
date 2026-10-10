#!/usr/bin/env python3
"""PRS installation verification: authenticated reads and temporary S3 probe, no BMC writes."""
import datetime,http.cookiejar,json,os,re,secrets,ssl,subprocess,sys,urllib.error,urllib.request,yaml
from pathlib import Path
B=Path('/raid/vince/deploy');C=B/'dps-install/config';R=B/'verification/reports/prs-installation.json'
os.umask(0o077)
os.environ.update({'KUBECONFIG':str(C/'kubernetes/kubeconfig.yaml'),'HELM_CONFIG_HOME':str(C/'helm'),'HELM_CACHE_HOME':str(B/'dps-install/data/helm-cache'),'HELM_DATA_HOME':str(B/'dps-install/data/helm-data'),
'DPSCTL_HOST':'api.dps.lab','DPSCTL_PORT':'443','DPSCTL_CA_CERT_PATH':str(C/'tls/ca.crt'),'DPSCTL_CREDENTIALS_PATH':str(C/'dpsctl/credentials.yaml'),'DPSCTL_LOG_FILE':str(B/'verification/logs/dpsctl.log')})
checks=[];private=[]
account=json.loads((C/'dps-access.json').read_text())
private.append(account['password'])
s3=json.loads((C/'prs/s3-credentials.json').read_text());private.extend([s3['admin_access_key_id'],s3['admin_secret_access_key']])
def clean(text):
 for v in private:
  if v:text=text.replace(v,'[REDACTED]')
 return re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b','[REDACTED_JWT]',text)
def run(args,stdin=None):
 r=subprocess.run(args,input=stdin,text=True,capture_output=True,timeout=90)
 if r.returncode:raise RuntimeError(clean(r.stderr[-1600:]or r.stdout[-1600:]))
 return r.stdout
def check(name,ok,details):
 checks.append({'name':name,'passed':bool(ok),'details':details});print(('PASS 'if ok else 'FAIL ')+name,flush=True)
def attempt(name,fn):
 try:fn()
 except Exception as e:check(name,False,{'error':clean(str(e))[:2000]})
def cli(*args):
 out=run(['dpsctl','--no-retry','--grpc-timeout','30s',*args]);x=json.loads(out[out.find('{'):])
 if x.get('status',{}).get('ok')is not True:raise RuntimeError(clean(json.dumps(x)))
 return x
def kube(resource):return json.loads(run(['kubectl','--context','dps-l20-12','-n','dps','get',resource,'-o','json']))
def exec_code(pod,container,code):
 out=run(['kubectl','--context','dps-l20-12','-n','dps','exec','-i',pod,'-c',container,'--','python3','-'],code)
 return json.loads(next(line for line in reversed(out.splitlines())if line.startswith('{')))
def get(url):
 client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 with client.open(url,timeout=30)as r:return r.status,r.read()
pods=kube('pods')['items'];services=kube('services')['items']
controller=next(p for p in pods if p['metadata']['name'].startswith('dps-power-controller-'))
config=next(p for p in pods if p['metadata']['name'].startswith('dps-power-config-'))
v=yaml.safe_load((C/'values.yaml').read_text())
check('prs-both-chart-switches-enabled',v['dps']['prs']['enabled']and v['power-steering']['enabled'],{'dps_prs':True,'power_steering':True})
def release_check():
 x=json.loads(run(['helm','--kube-context','dps-l20-12','list','-n','dps','-o','json']))
 check('helm-dps-deployed',len(x)==1 and x[0]['status']=='deployed'and x[0]['chart']=='dps-0.9.0',[{k:r[k]for k in ['name','revision','status','chart']}for r in x])
attempt('helm-release',release_check)
states=[{'name':p['metadata']['name'],'phase':p['status']['phase'],'ready':all(c['ready']for c in p['status'].get('containerStatuses',[])),'restarts':sum(c['restartCount']for c in p['status'].get('containerStatuses',[]))}for p in pods]
check('core-agent-ui-prs-seaweedfs-ready',len(states)==9 and all(p['phase']=='Running'and p['ready']for p in states),states)
check('no-bundled-postgresql',not any('postgres' in p['metadata']['name']for p in pods),{'external_postgresql':True})
def pv_check():
 claims=kube('pvc')['items'];selected=[p for p in claims if 'seaweedfs'in p['metadata']['name']]
 check('three-seaweedfs-pvc-bound',len(selected)==3 and all(p['status']['phase']=='Bound'for p in selected),[{'name':p['metadata']['name'],'phase':p['status']['phase'],'size':p['status']['capacity']['storage']}for p in selected])
 volumes=kube('pv')['items'];paths=[]
 for c in selected:
  pv=next(p for p in volumes if p['metadata']['name']==c['spec']['volumeName']);paths.append(pv['spec'].get('local',pv['spec'].get('hostPath',{})).get('path',''))
 check('s3-persistent-data-under-project',len(paths)==3 and all(p.startswith(str(B/'dps-install/data/kubernetes/storage'))for p in paths),paths)
 hostpaths=[v['hostPath']['path']for p in pods if 'seaweedfs'in p['metadata']['name'] for v in p['spec'].get('volumes',[])if 'hostPath'in v]
 check('seaweedfs-no-unmanaged-hostpaths',not hostpaths,{'hostpaths':hostpaths})
attempt('storage-persistence',pv_check)
def settings_check():
 settings=cli('settings','list')['settings']
 check('persisted-global-prs-enabled',settings.get('prs_enabled')=='true',settings)
 check('headroom-and-scheduler-effective',float(settings['prs_headroom_percent'])==-15 and float(settings['prs_scheduler_interval_seconds'])==5,{'headroom_percent':settings['prs_headroom_percent'],'scheduler_seconds':settings['prs_scheduler_interval_seconds']})
 tops=cli('topology','list').get('topologies',[]);rg=cli('resource-group','list').get('resource_groups',[])
 check('four-rack-topology-inactive',len(tops)==1 and tops[0]['topology_name']=='dps-gb300-4rack'and not tops[0].get('is_active',False)and len(tops[0].get('leaf_node_names',[]))==72,{'topology':'dps-gb300-4rack','active':False,'computers':len(tops[0].get('leaf_node_names',[]))if tops else 0})
 check('no-resource-groups-or-power-domains-assigned',len(rg)==0,{'resource_groups':len(rg)})
attempt('effective-settings-and-topology',settings_check)
roots={}
for name,port in [('config',8000),('controller',8001)]:
 service=next(s for s in services if s['metadata']['name']=='dps-power-'+name)
 roots[name]='http://'+service['spec']['clusterIP']+':'+str(port)
 for kind in ['startup','live','ready']:
  def health(name=name,kind=kind):
   status,body=get(roots[name]+'/health/'+kind)
   check(name+'-health-'+kind,status==200,{'http_status':status})
  attempt(name+'-health-'+kind,health)
 def metrics(name=name):
  status,body=get(roots[name]+'/metrics')
  check(name+'-metrics-readable',status==200 and bool(body),{'http_status':status,'bytes':len(body)})
 attempt(name+'-metrics-readable',metrics)
def domains():
 status,body=get(roots['config']+'/api/v1/domains?limit=10000');x=json.loads(body)
 check('prs-config-domain-list-empty',status==200 and x.get('items')==[],{'http_status':status,'domain_count':len(x.get('items',[]))})
 status,body=get(roots['controller']+'/api/v1/scheduler');x=json.loads(body)
 check('prs-controller-scheduler-healthy',status==200 and x.get('status')in ['idle','running'] and x.get('iteration_count',0)>0 and bool(x.get('next_run_at')) and bool(x.get('last_run_at')) and x.get('last_error')is None,{'http_status':status,**{k:x.get(k)for k in ['status','iteration_count','next_run_at','last_run_at','last_error']}})
attempt('prs-domain-and-scheduler',domains)
def actual_controller_auth():
 code="""import json
from loguru import logger
logger.remove()
from controller.core.settings import settings
from controller.power_control.components.cluster.dps.dps import DpsCluster
s=settings.cluster.dps
assert not s.tls.insecure and not s.tls.skip_verify and s.tls.ca_cert_path
assert s.auth.enabled
cluster=DpsCluster(s)
r=cluster._api.topology.list_topologies()
assert r.get('status',{}).get('ok')is True
print(json.dumps({'controller_dps_auth':'passed','topology_count':len(r.get('topologies',[]))}))
"""
 x=exec_code(controller['metadata']['name'],'controller',code)
 check('actual-controller-ldap-tls-dps-read',x.get('controller_dps_auth')=='passed'and x.get('topology_count')==1,x)
attempt('actual-controller-ldap-tls-dps-read',actual_controller_auth)
def database():
 sql="SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (SELECT a.datname,a.client_addr::text,a.usename,s.ssl,s.version FROM pg_stat_activity a JOIN pg_stat_ssl s ON a.pid=s.pid WHERE a.datname IN ('dps_prs_config','dps_prs_config_staged','dps_prs_controller') AND a.usename='dps') t;"
 rows=json.loads(run(['docker','exec','-u','postgres','dps-postgresql','psql','-X','-A','-t','-U','postgres','-d','postgres','-c',sql]))
 expected={'dps_prs_config','dps_prs_config_staged','dps_prs_controller'}
 check('actual-prs-application-postgresql-tls',bool(rows)and all(r['ssl']for r in rows)and expected.issubset({r['datname']for r in rows}),{'sessions':rows,'source_address_note':'Docker bridge SNAT presents 172.30.90.1 to PostgreSQL; direct Pod probes separately verify each Pod configuration.'})
 counts={}
 for db in ['dps_prs_config','dps_prs_config_staged','dps_prs_controller']:
  counts[db]=int(run(['docker','exec','-u','postgres','dps-postgresql','psql','-X','-A','-t','-U','postgres','-d',db,'-c',"SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';"]).strip())
 check('three-prs-database-schema-migrations',all(v>0 for v in counts.values()),counts)
attempt('actual-pod-database-tls-and-migrations',database)
def actual_pod_database(pod,container):
 code="""import json,os,psycopg2
assert os.environ.get('PGSSLMODE')=='verify-full'
assert os.path.isfile(os.environ['PGSSLROOTCERT'])
names=[os.environ['DATABASE__NAME']]
if os.environ.get('DATABASE__STAGED_NAME'):names.append(os.environ['DATABASE__STAGED_NAME'])
result=[]
for name in names:
 connection=psycopg2.connect(host=os.environ['DATABASE__HOST'],port=os.environ['DATABASE__PORT'],user=os.environ['DATABASE__USER'],password=os.environ['DATABASE__PASSWORD'],dbname=name,connect_timeout=15)
 try:
  assert connection.get_dsn_parameters()['sslmode']=='verify-full'
  with connection.cursor()as cursor:
   cursor.execute('SELECT ssl,version FROM pg_stat_ssl WHERE pid=pg_backend_pid()')
   ssl_used,version=cursor.fetchone()
   assert ssl_used
   result.append({'database':name,'ssl':ssl_used,'tls_version':version,'sslmode':'verify-full'})
 finally:connection.close()
print(json.dumps({'databases':result,'all_verify_full':True}))
"""
 x=exec_code(pod['metadata']['name'],container,code)
 expected=2 if container=='config' else 1
 check('actual-'+container+'-pod-postgresql-verify-full',x.get('all_verify_full')is True and len(x.get('databases',[]))==expected,x)
for pod,container in [(config,'config'),(controller,'controller')]:
 attempt('actual-'+container+'-pod-postgresql-verify-full',lambda pod=pod,container=container:actual_pod_database(pod,container))
def s3_check():
 code="""import boto3,hashlib,json,os,secrets,urllib.request,urllib.error
from botocore.config import Config
endpoint=os.environ['AWS_ENDPOINT_URL']
client=boto3.client('s3',endpoint_url=endpoint,region_name='us-east-1',config=Config(signature_version='s3v4',s3={'addressing_style':'path'}))
bucket='dps-prs';client.head_bucket(Bucket=bucket)
key='verification/'+secrets.token_hex(16);payload=secrets.token_bytes(64);written=False
try:
 client.put_object(Bucket=bucket,Key=key,Body=payload);written=True
 actual=client.get_object(Bucket=bucket,Key=key)['Body'].read()
 assert hashlib.sha256(actual).digest()==hashlib.sha256(payload).digest()
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 try:
  with opener.open(endpoint+'/'+bucket+'/'+key,timeout=15)as r:anonymous=r.status
 except urllib.error.HTTPError as e:anonymous=e.code
 assert anonymous in [401,403]
finally:
 if written:client.delete_object(Bucket=bucket,Key=key)
print(json.dumps({'bucket':bucket,'put_get_delete':True,'anonymous_http_status':anonymous,'temporary_object_deleted':True}))
"""
 x=exec_code(controller['metadata']['name'],'controller',code)
 check('s3-authenticated-put-get-delete',x.get('put_get_delete')is True and x.get('temporary_object_deleted')is True,x)
 check('s3-anonymous-object-read-denied',x.get('anonymous_http_status')in [401,403],{'http_status':x.get('anonymous_http_status')})
attempt('s3-object-storage',s3_check)
def rbac():
 sa=controller['spec']['serviceAccountName']
 x=run(['kubectl','--context','dps-l20-12','-n','dps','auth','can-i','get','secret/dps-prs-dps-auth','--as','system:serviceaccount:dps:'+sa]).strip()
 check('controller-secret-rbac',x=='yes',{'service_account':sa,'can_get_own_ldap_secret':x})
attempt('controller-rbac',rbac)
def ldap_regression():
 r=run(['bash',str(B/'dps-install/scripts/dps-login.sh')])
 check('production-ldap-login-after-prs-upgrade','LDAP login successful'in r,{'username':account['username']})
 x=cli('verify','--dps-server','--database','--auth')
 flags={k:v.get('healthy')for k,v in x.items()if k!='status'and isinstance(v,dict)}
 check('dps-server-database-auth-health',bool(flags)and all(flags.values()),flags)
 x=json.loads(run(['dpsctl','--no-retry','agent','list']))
 check('agent-mtls-still-connected',any(a.get('agent_id')=='gb300-lab-agent'and a.get('connected')for a in x),{'agent':'gb300-lab-agent'})
 jar=http.cookiejar.CookieJar()
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(C/'tls/ca.crt'))),urllib.request.HTTPCookieProcessor(jar))
 def request(path,body=None,token=None):
  headers={'Origin':'https://ui.dps.lab','X-Client-Id':'dps-ui-v2','X-Client-Version':'0.9.0','Content-Type':'application/json','X-DPS-Session':'1'}
  if token:headers['Authorization']='Bearer '+token
  req=urllib.request.Request('https://ui.dps.lab'+path,data=json.dumps(body).encode()if body is not None else None,headers=headers,method='POST')
  try:
   with opener.open(req,timeout=30)as r:status=r.status;raw=r.read()
  except urllib.error.HTTPError as e:status=e.code;raw=e.read()
  return status,json.loads(raw)if raw else {}
 token=None
 try:
  status,x=request('/api/session/login',{'username':account['username'],'password':account['password']});token=x.get('accessToken')
  if token:private.append(token)
  check('ui-real-ldap-login-after-prs',status==200 and bool(token),{'http_status':status,'session_cookie_present':len(jar)>0})
 finally:
  if token:
   status,_=request('/api/session/logout',token=token)
   check('ui-test-session-logout',status==204,{'http_status':status})
  jar.clear()
 status,x=request('/api/session/login',{'username':account['username'],'password':'wrong-'+secrets.token_urlsafe(18)})
 check('ui-wrong-ldap-password-still-rejected',status==401 and not x.get('accessToken'),{'http_status':status})
attempt('ldap-and-core-regression',ldap_regression)
for path in [B/'verification/logs/dpsctl.log']:
 if path.exists():path.write_text(clean(path.read_text(errors='replace')));path.chmod(0o600)
report={'checked_at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'scope':'PRS deployment/runtime switch and real Pod integration; empty domain with inactive topology, no BMC or power-policy writes','passed':all(c['passed']for c in checks),'counts':{'passed':sum(c['passed']for c in checks),'total':len(checks)},'checks':checks,'topology_active':False,'resource_groups':0,'bmc_writes':False,'dynamic_power_control_verified':False}
R.write_text(clean(json.dumps(report,indent=2))+'\n');R.chmod(0o600)
print(json.dumps({'passed':report['passed'],'counts':report['counts'],'report':str(R)}))
sys.exit(0 if report['passed']else 1)
