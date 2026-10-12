#!/usr/bin/env python3
"""Prepare stable lab TLS/JWT Secrets; refuse incomplete or mismatched existing pairs."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
from deployment_context import context_from_cli
ctx = context_from_cli()
import os,subprocess,yaml
os.umask(0o077)
B=ctx.runtime_root;C=B/'dps-install/config';T=C/'tls';T.mkdir(parents=True,exist_ok=True)
full=ctx.settings['fullname'];ns=ctx.settings['namespace'];ip=ctx.settings['host_ip']
leaves=[
 ('server',full+'-server-grpc','serverAuth',['DNS:'+ctx.settings['api_name'], 'DNS:'+full+'-server-grpc', 'DNS:'+full+'-server-grpc.'+ns, 'DNS:'+full+'-server-grpc.'+ns+'.svc', 'DNS:'+full+'-server-grpc.'+ns+'.svc.cluster.local', 'IP:'+ip]),
 ('agent',ctx.settings['agent_id'],'clientAuth',['DNS:'+ctx.settings['agent_id']]),
 ('ingress',ctx.settings['ui_name'],'serverAuth',['DNS:'+ctx.settings['ui_name'],'DNS:'+ctx.settings['api_name'],'IP:'+ip]),
]
def run(*args):
 return subprocess.run(['openssl',*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
def check_pair(name):
 key,crt=T/(name+'.key'),T/(name+'.crt')
 if key.exists()!=crt.exists():raise RuntimeError('Incomplete existing TLS pair: '+name+'; restore the missing file before rerunning.')
 if key.exists():
  if run('pkey','-in',str(key),'-pubout')!=run('x509','-in',str(crt),'-noout','-pubkey'):raise RuntimeError('TLS key/certificate mismatch: '+name)
  run('x509','-in',str(crt),'-noout','-checkend','86400')
recorded_identity=(T/'jwt-private-key.pem').exists() or (C/'dps-bootstrap.json').exists() or any(
 (T/(name+suffix)).exists() for name,_,_,_ in leaves for suffix in ['.key','.crt']) or any(T.glob('*-tls-secret.yaml'))
for name,_,_,_ in leaves:
 if not (T/(name+'.key')).exists() and not (T/(name+'.crt')).exists() and recorded_identity:
  raise RuntimeError('Recorded DPS leaf identity is missing both files: '+name+'; restore rather than generate a replacement.')
for name in ['ca']+[leaf[0] for leaf in leaves]:check_pair(name)
existing_leaves=any((T/(name+suffix)).exists() for name,_,_,_ in leaves for suffix in ['.key','.crt'])
if existing_leaves and (not (T/'ca.key').exists() or not (T/'jwt-private-key.pem').exists()):
 raise RuntimeError('Existing DPS TLS/JWT identity is incomplete; restore missing material rather than replace it.')
if not (T/'ca.key').exists():
 run('genrsa','-out',str(T/'ca.key'),'3072')
 run('req','-new','-x509','-sha256','-days','365','-key',str(T/'ca.key'),'-out',str(T/'ca.crt'),'-subj','/CN=DPS-'+ctx.settings['host_name']+'-Lab-CA','-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign')
for name,cn,eku,sans in leaves:
 key,crt=T/(name+'.key'),T/(name+'.crt')
 if not key.exists():
  run('genrsa','-out',str(key),'3072')
  csr,ext=T/(name+'.csr'),T/(name+'.ext')
  ext.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage='+eku+'\nsubjectAltName='+','.join(sans)+'\n')
  run('req','-new','-key',str(key),'-out',str(csr),'-subj','/CN='+cn)
  run('x509','-req','-in',str(csr),'-CA',str(T/'ca.crt'),'-CAkey',str(T/'ca.key'),'-CAcreateserial','-out',str(crt),'-days','365','-sha256','-extfile',str(ext))
 check_pair(name)
 run('verify','-CAfile',str(T/'ca.crt'),'-purpose','sslclient' if eku=='clientAuth' else 'sslserver',str(crt))
 subject=run('x509','-in',str(crt),'-noout','-subject','-nameopt','RFC2253').decode().strip()
 if subject!='subject=CN='+cn:raise RuntimeError('Unexpected certificate subject: '+name)
 for san in sans:
  run('x509','-in',str(crt),'-noout','-checkhost' if san.startswith('DNS:') else '-checkip',san.split(':',1)[1])
for key in T.glob('*.key'):key.chmod(0o600)
for crt in T.glob('*.crt'):crt.chmod(0o644)
def secret_file(p,secret):
 temporary=p.with_name('.'+p.name+'.tmp')
 temporary.write_text(yaml.safe_dump(secret,sort_keys=False));temporary.chmod(0o600);temporary.replace(p)
for name,leaf in [('dps-server-tls','server'),('dps-agent-tls','agent'),('dps-ingress-tls','ingress')]:
 secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':ctx.settings['namespace']},'type':'kubernetes.io/tls','stringData':{k:(T/f).read_text() for k,f in [('ca.crt','ca.crt'),('tls.crt',leaf+'.crt'),('tls.key',leaf+'.key')]}}
 secret_file(T/(name+'-secret.yaml'),secret)
key=T/'jwt-private-key.pem'
if not key.exists():run('genrsa','-out',str(key),'3072')
key.chmod(0o600);run('pkey','-in',str(key),'-check','-noout')
secret_file(T/'dps-jwt-keys-secret.yaml',{'apiVersion':'v1','kind':'Secret','metadata':{'name':'dps-jwt-keys','namespace':ctx.settings['namespace']},'type':'Opaque','stringData':{'private-key.pem':key.read_text()}})
secret_file(C/'bmc-ca-secret.yaml',{'apiVersion':'v1','kind':'Secret','metadata':{'name':'dps-bmc-ca','namespace':ctx.settings['namespace']},'type':'Opaque','stringData':{'ca.crt':(C/'simulator-ca.crt').read_text()}})
p=C/'bmc-shared-secret.yaml';data=yaml.safe_load(p.read_text())
data['metadata']['namespace']=ctx.settings['namespace'];data['metadata'].setdefault('labels',{})['app.kubernetes.io/component']='bmc-credentials'
secret_file(p,data)
print('TLS pairs, validity, names and purposes verified; stable external Secrets prepared. Private files mode 600.')
