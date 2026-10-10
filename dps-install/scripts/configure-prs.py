#!/usr/bin/env python3
"""Prepare PRS/Power Steering 2.1.0 while preserving existing DPS identities and topology."""
import json,os,secrets,subprocess,yaml
from pathlib import Path
B=Path('/raid/vince/deploy');C=B/'dps-install/config';P=C/'prs'
os.umask(0o077);P.mkdir(parents=True,exist_ok=True,mode=0o700)
v=yaml.safe_load((C/'values.yaml').read_text())
assert v['dps']['auth']['authenticatorType']=='ldap' and v['dps']['ldap']['enabled']
assert not v['postgresql']['enabled'] and v['global']['postgresql']['sslMode']=='verify-full'
assert v['global']['postgresql']['host']=='10.6.131.43'
account=json.loads((C/'dps-access.json').read_text())
assert account['username']=='dps-lab' and account['authentication']=='ldap'
def save(path,value):
 path.write_text(yaml.safe_dump(value,sort_keys=False) if path.suffix=='.yaml' else json.dumps(value,indent=2)+'\n');path.chmod(0o600)
credentials=P/'s3-credentials.json'
if credentials.exists():s3=json.loads(credentials.read_text())
else:
 s3={'bucket':'dps-prs','secret_name':'dps-prs-s3','admin_access_key_id':secrets.token_urlsafe(18),'admin_secret_access_key':secrets.token_urlsafe(40)}
 save(credentials,s3)
assert s3['bucket']=='dps-prs' and s3['secret_name']=='dps-prs-s3'
identity={'identities':[{'name':'dps-prs','credentials':[{'accessKey':s3['admin_access_key_id'],'secretKey':s3['admin_secret_access_key']}],'actions':['Admin','Read','Write']}]}
save(P/'s3-secret.yaml',{'apiVersion':'v1','kind':'Secret','metadata':{'name':'dps-prs-s3','namespace':'dps'},'type':'Opaque','stringData':{'admin_access_key_id':s3['admin_access_key_id'],'admin_secret_access_key':s3['admin_secret_access_key'],'seaweedfs_s3_config':json.dumps(identity)}})
save(P/'dps-auth-secret.yaml',{'apiVersion':'v1','kind':'Secret','metadata':{'name':'dps-prs-dps-auth','namespace':'dps'},'type':'Opaque','stringData':{'ldap-credentials':json.dumps({'username':account['username'],'password':account['password']})}})
v['global']['database']={'user':'dps','names':{'config':'dps_prs_config','configStaged':'dps_prs_config_staged','controller':'dps_prs_controller'}}
v['global']['storage']={'bucketName':'dps-prs','s3Endpoint':'','region':'us-east-1','existingSecret':'dps-prs-s3','accessKeyIdKey':'admin_access_key_id','secretAccessKeyKey':'admin_secret_access_key'}
v['dps']['prs']={'enabled':True,'hostPort':'http://dps-power-config.dps.svc.cluster.local:8000','controllerHostPort':'http://dps-power-controller.dps.svc.cluster.local:8001','headroomPercent':-15.0,'schedulerIntervalSeconds':5.0,'historyWindowSize':0,'predictorSafetyGapWatts':0.0}
extra=[{'name':'PGSSLMODE','value':'verify-full'},{'name':'PGSSLROOTCERT','value':'/secrets/postgresql/ca.crt'}]
vol=[{'name':'postgresql-ca','secret':{'secretName':'dps-postgresql-ca','items':[{'key':'ca.crt','path':'ca.crt'}]}}]
mount=[{'name':'postgresql-ca','mountPath':'/secrets/postgresql','readOnly':True}]
pg=json.loads(subprocess.check_output(['docker','inspect','dps-postgresql'],text=True))[0]
assert pg['State']['Running'],'Independent PostgreSQL must be running'
bridge=pg['NetworkSettings']['Networks']['dps-postgresql-net']['IPAddress']
assert bridge=='172.30.90.2','Unexpected PostgreSQL bridge endpoint; review the deployment network'
egress=[{'to':[{'ipBlock':{'cidr':'10.6.131.43/32'}}],'ports':[{'port':15432,'protocol':'TCP'}]},
 {'to':[{'ipBlock':{'cidr':bridge+'/32'}}],'ports':[{'port':5432,'protocol':'TCP'}]}]
controller_egress=egress+[{'to':[{'ipBlock':{'cidr':'10.6.131.43/32'}}],'ports':[{'port':6443,'protocol':'TCP'}]}]
v['power-steering']={'enabled':True,'postgresql':{'enabled':False},'global':{'image':{'tag':'2.1.0','pullPolicy':'IfNotPresent'},'lgtm':False},
 'config':{'extraEnv':extra,'extraVolumes':vol,'extraVolumeMounts':mount,'extraEgressRules':egress},
 'controller':{'cluster':{'shadowMode':False,'dps':{'host':'dps-server-grpc','port':8080,'tls':{'insecure':False,'skipVerify':False,'caCertPath':'/secrets/dps/ca.crt'},'auth':{'enabled':True,'secretName':'dps-prs-dps-auth'}}},
  'extraEnv':extra,'extraVolumes':vol+[{'name':'dps-ca','secret':{'secretName':'dps-server-tls','items':[{'key':'ca.crt','path':'ca.crt'}]}}],
  'extraVolumeMounts':mount+[{'name':'dps-ca','mountPath':'/secrets/dps','readOnly':True}],'extraEgressRules':controller_egress},
 'seaweedfs':{'enabled':True,'master':{'logs':{'type':'emptyDir'}},'filer':{'logs':{'type':'emptyDir'}},'volume':{'logs':{'type':'emptyDir'}},'s3':{'existingConfigSecret':'dps-prs-s3','createBuckets':[{'name':'dps-prs','anonymousRead':False}],'logs':{'type':'emptyDir'}}}}
save(C/'values.yaml',v)
print('PRS configuration and external S3/LDAP Secrets prepared. Existing identities and topology preserved.')
