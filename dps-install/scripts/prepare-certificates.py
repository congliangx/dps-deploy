#!/usr/bin/env python3
"""Prepare stable lab TLS/JWT Secrets; refuse incomplete or mismatched existing pairs."""
from pathlib import Path
import os,subprocess,yaml
os.umask(0o077)
B=Path('/raid/vince/deploy');C=B/'dps-install/config';T=C/'tls';T.mkdir(exist_ok=True)
leaves=[
 ('server','dps-server-grpc','serverAuth',['DNS:api.dps.lab','DNS:dps-server-grpc','DNS:dps-server-grpc.dps','DNS:dps-server-grpc.dps.svc','DNS:dps-server-grpc.dps.svc.cluster.local','IP:10.6.131.43']),
 ('agent','gb300-lab-agent','clientAuth',['DNS:gb300-lab-agent']),
 ('ingress','ui.dps.lab','serverAuth',['DNS:ui.dps.lab','DNS:api.dps.lab','IP:10.6.131.43']),
]
def run(*args):
 return subprocess.run(['openssl',*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
def check_pair(name):
 key,crt=T/(name+'.key'),T/(name+'.crt')
 if key.exists()!=crt.exists():raise RuntimeError('Incomplete existing TLS pair: '+name+'; restore the missing file before rerunning.')
 if key.exists():
  if run('pkey','-in',str(key),'-pubout')!=run('x509','-in',str(crt),'-noout','-pubkey'):raise RuntimeError('TLS key/certificate mismatch: '+name)
  run('x509','-in',str(crt),'-noout','-checkend','86400')
for name in ['ca']+[leaf[0] for leaf in leaves]:check_pair(name)
if not (T/'ca.key').exists():
 run('genrsa','-out',str(T/'ca.key'),'3072')
 run('req','-new','-x509','-sha256','-days','365','-key',str(T/'ca.key'),'-out',str(T/'ca.crt'),'-subj','/CN=DPS-L20-12-Lab-CA','-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign')
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
 secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':'dps'},'type':'kubernetes.io/tls','stringData':{k:(T/f).read_text() for k,f in [('ca.crt','ca.crt'),('tls.crt',leaf+'.crt'),('tls.key',leaf+'.key')]}}
 secret_file(T/(name+'-secret.yaml'),secret)
key=T/'jwt-private-key.pem'
if not key.exists():run('genrsa','-out',str(key),'3072')
key.chmod(0o600);run('pkey','-in',str(key),'-check','-noout')
secret_file(T/'dps-jwt-keys-secret.yaml',{'apiVersion':'v1','kind':'Secret','metadata':{'name':'dps-jwt-keys','namespace':'dps'},'type':'Opaque','stringData':{'private-key.pem':key.read_text()}})
secret_file(C/'bmc-ca-secret.yaml',{'apiVersion':'v1','kind':'Secret','metadata':{'name':'dps-bmc-ca','namespace':'dps'},'type':'Opaque','stringData':{'ca.crt':(C/'simulator-ca.crt').read_text()}})
p=C/'bmc-shared-secret.yaml';data=yaml.safe_load(p.read_text())
data['metadata']['namespace']='dps';data['metadata'].setdefault('labels',{})['app.kubernetes.io/component']='bmc-credentials'
secret_file(p,data)
print('TLS pairs, validity, names and purposes verified; stable external Secrets prepared. Private files mode 600.')
