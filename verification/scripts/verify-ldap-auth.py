#!/usr/bin/env python3
"""LDAP positive/negative DPS authentication checks, without hardware operations."""
import base64, http.cookiejar, json, os, re, secrets, ssl, subprocess, sys
import urllib.error, urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml
os.umask(0o077)
B=Path('/raid/vince/deploy');C=B/'dps-install/config'
REPORT=B/'verification/reports/dps-ldap-auth.json'
CONTEXT='dps-l20-12'
os.environ.update({'KUBECONFIG':str(C/'kubernetes/kubeconfig.yaml'),
 'DPSCTL_HOST':'api.dps.lab','DPSCTL_PORT':'443','DPSCTL_CA_CERT_PATH':str(C/'tls/ca.crt'),
 'DPSCTL_CREDENTIALS_PATH':str(C/'dpsctl/credentials.yaml'),
 'DPSCTL_LOG_FILE':str(B/'verification/logs/dpsctl.log')})
account=json.loads((C/'dps-access.json').read_text())
ldap=json.loads((C/'ldap/credentials.json').read_text())
migration=json.loads((C/'ldap-auth-migration.json').read_text())
private=[account['password'],ldap['noaccess_password']]
checks=[]
work=B/'verification/archive/ldap-auth-tests'/datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%dT%H%M%S%z')
work.mkdir(parents=True,mode=0o700)
def clean(s):
 for value in private:
  if isinstance(value,str) and value:s=s.replace(value,'[REDACTED]')
 return re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b','[REDACTED_JWT]',s)
def check(name,ok,details):
 checks.append({'name':name,'passed':bool(ok),'details':details})
 print(('PASS ' if ok else 'FAIL ')+name,flush=True)
def parse_cli(r):
 s=r.stdout.strip();start=s.find('{')
 try:return json.loads(s[start:]) if start>=0 else {}
 except ValueError:return {}
def cli(args,stdin=None,path=None):
 command=['dpsctl','--no-retry','--grpc-timeout','30s']
 if path:command+=['--credentials-path',str(path),'--log-file',str(work/'dpsctl.log')]
 return subprocess.run(command+args,input=stdin,capture_output=True,text=True,timeout=65)
def kube(resource):
 return json.loads(subprocess.check_output(['kubectl','--context',CONTEXT,'-n','dps','get',resource,'-o','json'],text=True))
def leaves(x):
 if isinstance(x,dict):return [s for v in x.values() for s in leaves(v)]
 if isinstance(x,list):return [s for v in x for s in leaves(v)]
 return [x] if isinstance(x,str) else []
def token_present(x):
 return any(s.count('.')==2 and s.startswith('eyJ') for s in leaves(x))
def decode(token):
 raw=token.split('.')[1]
 return json.loads(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
def opener(cookies=None):
 handlers=[urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(C/'tls/ca.crt')))]
 if cookies is not None:handlers.append(urllib.request.HTTPCookieProcessor(cookies))
 return urllib.request.build_opener(*handlers)
def http_request(client,url,body=None,token=None,session=False):
 headers={'Accept':'application/json','Content-Type':'application/json'}
 if url.startswith('https://ui.dps.lab/'):
  headers.update({'Origin':'https://ui.dps.lab','X-Client-Id':'dps-ui-v2','X-Client-Version':'0.9.0'})
 if token:headers['Authorization']='Bearer '+token
 if session:headers['X-DPS-Session']='1'
 data=json.dumps(body).encode() if body is not None else None
 req=urllib.request.Request(url,data=data,headers=headers,method='POST')
 try:
  with client.open(req,timeout=35) as response:code=response.status;raw=response.read()
 except urllib.error.HTTPError as e:code=e.code;raw=e.read()
 try:result=json.loads(raw) if raw else {}
 except ValueError:result={}
 return code,result
def status_ok(x):return x.get('status',{}).get('ok') is True
def attempt(name,func):
 try:func()
 except Exception as e:check(name,False,{'error':clean(str(e))[:1000]})

v=yaml.safe_load((C/'values.yaml').read_text())
check('configured-ldap-authenticator',v['dps']['auth']['authenticatorType']=='ldap' and v['dps']['ldap']['enabled'] and v['dps']['ldap']['defaultRole']=='' and v['dps']['auth']['auth_required_groups']=='dcpower-users',
 {'authenticator':v['dps']['auth']['authenticatorType'],'required_groups':v['dps']['auth']['auth_required_groups'],'default_role':v['dps']['ldap']['defaultRole']})
def login_valid():
 r=cli(['login','--username',account['username'],'--password-stdin'],account['password']+'\n')
 x=parse_cli(r)
 check('cli-valid-ldap-password',r.returncode==0 and status_ok(x),{'username':account['username'],'exit_code':r.returncode,'status_ok':status_ok(x)})
 if r.returncode or not status_ok(x):raise RuntimeError(clean(r.stderr or r.stdout))
 p=C/'dpsctl/credentials.yaml';p.chmod(0o600)
 t=yaml.safe_load(p.read_text())['token']['access_token'];private.append(t)
 claims=decode(t)
 roles=claims.get('roles',[])
 member=claims.get('memberOf',[])
 check('ldap-admin-role-from-group','admin' in roles and any('dcpower-users' in x for x in ([member] if isinstance(member,str) else member)),
  {'username':claims.get('preferred_username'),'roles':roles,'authorization_group_present':any('dcpower-users' in x for x in ([member] if isinstance(member,str) else member))})
 check('cli-credentials-private',p.stat().st_mode&0o777==0o600,{'mode':'0600'})
 r=cli(['topology','list']);x=parse_cli(r)
 tops=x.get('topologies',[]);chosen=[t for t in tops if t.get('topology_name')=='dps-gb300-4rack']
 check('cli-authorized-topology-read',r.returncode==0 and status_ok(x) and len(chosen)==1,
  {'topology_count':len(tops),'expected_found':len(chosen)==1})
 check('four-rack-topology-preserved-inactive',len(chosen)==1 and not chosen[0].get('is_active',False) and len(chosen[0].get('leaf_node_names',[]))==72,
  {'name':'dps-gb300-4rack','active':chosen[0].get('is_active',False) if chosen else None,'leaf_nodes':len(chosen[0].get('leaf_node_names',[])) if chosen else 0})
attempt('cli-positive-flow',login_valid)
cases=[
 ('wrong-password',account['username'],'wrong-'+secrets.token_urlsafe(20)),
 ('unknown-user','dps-does-not-exist-'+secrets.token_hex(6),secrets.token_urlsafe(24)),
 ('empty-password',account['username'],''),
 ('real-user-outside-authorized-group',ldap['noaccess_username'],ldap['noaccess_password'])]
for label,user,password in cases:
 def cli_negative(label=label,user=user,password=password):
  private.append(password)
  path=work/(label+'.yaml')
  r=cli(['login','--username',user,'--password-stdin'],password+'\n',path)
  x=parse_cli(r)
  issued=False
  if path.exists():
   y=yaml.safe_load(path.read_text()) or {}
   issued=bool(y.get('token',{}).get('access_token'))
  if label=='real-user-outside-authorized-group':
   credentials=y.get('token',{})
   private.extend(credentials.values())
   claims=decode(credentials['access_token']) if issued else {}
   check('cli-group-outside-user-authenticated-without-role',r.returncode==0 and status_ok(x) and issued and claims.get('roles',[])==[] and claims.get('memberOf',[])==[],
    {'exit_code':r.returncode,'status_ok':status_ok(x),'credentials_issued':issued,'roles':claims.get('roles',[]),'memberOf':claims.get('memberOf',[])})
   protected=cli(['topology','list'],path=path);denied=parse_cli(protected)
   check('cli-group-outside-user-authorization-denied',protected.returncode!=0 and not status_ok(denied) and denied.get('status',{}).get('error',{}).get('code')=='AUTHORIZATION_FAILED',
    {'exit_code':protected.returncode,'status_ok':status_ok(denied),'error_code':denied.get('status',{}).get('error',{}).get('code')})
   if issued:
    service=kube('service/dps-server-http')
    endpoint='http://'+service['spec']['clusterIP']+':'+str(next(port['port']for port in service['spec']['ports'] if port['name']=='dps-http'))
    code,result=http_request(opener(),endpoint+'/nvidia.dcpower.v1.AuthService/Logout',{'accessToken':credentials['access_token'],'refreshToken':credentials['refresh_token']})
    check('cli-group-outside-test-session-logout',code==200 and not (result.get('status') and not status_ok(result)),{'http_status':code})
  else:
   check('cli-reject-'+label,r.returncode!=0 and not status_ok(x) and not issued,
    {'exit_code':r.returncode,'status_ok':status_ok(x),'credentials_issued':issued,'error_code':x.get('status',{}).get('error',{}).get('code')})
 attempt('cli-reject-'+label,cli_negative)
base='https://ui.dps.lab'
def ui_positive():
 jar=http.cookiejar.CookieJar();client=opener(jar);token=None
 try:
  code,x=http_request(client,base+'/api/session/login',{'username':account['username'],'password':account['password']},session=True)
  token=x.get('accessToken')
  if token:private.append(token)
  check('ui-valid-ldap-password',code==200 and bool(token),{'http_status':code,'access_token_present':bool(token),'ca_verified':True,'session_cookie_present':len(jar)>0})
  if not token:return
  code,x=http_request(client,base+'/api/nvidia.dcpower.v1.TopologyManagementService/ListTopologies',{},token)
  check('ui-authorized-topology-read',code==200 and status_ok(x) and any(t.get('topologyName')=='dps-gb300-4rack' for t in x.get('topologies',[])),
   {'http_status':code,'status_ok':status_ok(x),'topology_count':len(x.get('topologies',[]))})
 finally:
  if token:
   code,_=http_request(client,base+'/api/session/logout',None,token,True)
   check('ui-session-logout',code==204,{'http_status':code})
  jar.clear()
attempt('ui-positive-flow',ui_positive)
for label,user,password in cases:
 def ui_negative(label=label,user=user,password=password):
  jar=http.cookiejar.CookieJar();client=opener(jar)
  code,x=http_request(client,base+'/api/session/login',{'username':user,'password':password},session=True)
  issued=bool(x.get('accessToken')) or token_present(x)
  if label=='real-user-outside-authorized-group':
   token=x.get('accessToken')
   if token:private.append(token)
   claims=decode(token) if token else {}
   check('ui-group-outside-user-authenticated-without-role',code==200 and bool(token) and claims.get('roles',[])==[] and claims.get('memberOf',[])==[],
    {'http_status':code,'access_token_present':bool(token),'roles':claims.get('roles',[]),'memberOf':claims.get('memberOf',[])})
   if token:
    try:
     protected_code,protected=http_request(client,base+'/api/nvidia.dcpower.v1.TopologyManagementService/ListTopologies',{},token)
     check('ui-group-outside-user-authorization-denied',protected_code>=400 and not status_ok(protected),
      {'http_status':protected_code,'status_ok':status_ok(protected),'error_code':protected.get('status',{}).get('error',{}).get('code')})
    finally:
     logout_code,_=http_request(client,base+'/api/session/logout',None,token,True)
     check('ui-group-outside-test-session-logout',logout_code==204,{'http_status':logout_code})
  else:
   check('ui-reject-'+label,code>=400 and not issued and len(jar)==0,
    {'http_status':code,'access_token_present':issued,'session_cookie_count':len(jar)})
  jar.clear()
 attempt('ui-reject-'+label,ui_negative)
def old_token_rejection():
 oldpath=Path(migration['pre_change_archive'])/'dps-install/config/dpsctl/credentials.yaml'
 old=yaml.safe_load(oldpath.read_text())['token']
 private.extend([old['access_token'],old['refresh_token']])
 svc=kube('service/dps-server-http')
 root='http://'+svc['spec']['clusterIP']+':'+str(next(p['port']for p in svc['spec']['ports'] if p['name']=='dps-http'))
 client=opener()
 # Prove the same native RefreshToken request succeeds for a new LDAP session.
 profile=work/'valid-refresh.yaml'
 r=cli(['login','--username',account['username'],'--password-stdin'],account['password']+'\n',profile)
 if r.returncode or not status_ok(parse_cli(r)):
  raise RuntimeError('Could not create the isolated valid refresh session')
 fresh=yaml.safe_load(profile.read_text())['token']
 private.extend([fresh['access_token'],fresh['refresh_token']])
 code,new=http_request(client,root+'/nvidia.dcpower.v1.AuthService/RefreshToken',{'refreshToken':fresh['refresh_token']})
 tokens=[v for v in leaves(new) if v.count('.')==2 and v.startswith('eyJ')]
 private.extend(tokens)
 check('native-ldap-refresh-token-valid',code==200 and len(tokens)>=1,{'http_status':code,'token_returned':bool(tokens)})
 access=next((v for v in tokens if 'roles' in decode(v)),fresh['access_token'])
 refresh=next((v for v in tokens if 'roles' not in decode(v)),fresh['refresh_token'])
 logout_code,logout=http_request(client,root+'/nvidia.dcpower.v1.AuthService/Logout',{'accessToken':access,'refreshToken':refresh})
 check('native-test-session-logout',logout_code==200 and not (logout.get('status') and not status_ok(logout)),{'http_status':logout_code})
 code,x=http_request(client,root+'/nvidia.dcpower.v1.TopologyManagementService/ListTopologies',{},old['access_token'])
 check('evaluation-access-token-rejected',code>=400 and not status_ok(x),{'http_status':code,'new_token_returned':token_present(x)})
 code,x=http_request(client,root+'/nvidia.dcpower.v1.AuthService/RefreshToken',{'refreshToken':old['refresh_token']})
 check('evaluation-refresh-token-rejected',code>=400 and not token_present(x),{'http_status':code,'new_token_returned':token_present(x)})
attempt('evaluation-token-revocation',old_token_rejection)
def component_health():
 pods=[p for p in kube('pods')['items']if p['metadata']['name']=='dps-server-0' or p['metadata']['name'].startswith(('dps-server-agent-','dps-ui-'))]
 states=[{'name':p['metadata']['name'],'phase':p['status']['phase'],'ready':all(c['ready']for c in p['status'].get('containerStatuses',[]))}for p in pods]
 check('core-agent-ui-ready-after-auth-switch',len(states)==3 and all(p['phase']=='Running' and p['ready']for p in states),states)
 r=cli(['agent','list']);x=json.loads(r.stdout)
 check('agent-mtls-connection-preserved',r.returncode==0 and any(a.get('agent_id')=='gb300-lab-agent' and a.get('connected')for a in x),
  [{'agent_id':a.get('agent_id'),'connected':a.get('connected')}for a in x])
 r=cli(['verify','--dps-server','--database','--auth']);x=parse_cli(r)
 components={k:v.get('healthy')for k,v in x.items()if k!='status' and isinstance(v,dict)}
 check('server-database-ldap-auth-healthy',r.returncode==0 and status_ok(x) and bool(components) and all(components.values()),components)
attempt('post-auth-switch-health',component_health)
for p in [work/'dpsctl.log',B/'verification/logs/dpsctl.log']:
 if p.exists():
  p.write_text(clean(p.read_text(errors='replace')));p.chmod(0o600)
report={'checked_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
 'scope':'DPS CLI/UI positive and negative LDAP authentication, group authorization and old JWT revocation; no topology activation or BMC writes',
 'authentication':'ldap','ldap_endpoint':ldap['endpoint'],'username':account['username'],
 'checks':checks,'passed':all(x['passed']for x in checks),
 'counts':{'passed':sum(x['passed']for x in checks),'total':len(checks)},
 'topology_active':False,'hardware_writes':False}
REPORT.write_text(clean(json.dumps(report,indent=2))+'\n');REPORT.chmod(0o600)
print(json.dumps({'report':str(REPORT),'passed':report['passed'],'counts':report['counts']}))
sys.exit(0 if report['passed']else 1)
