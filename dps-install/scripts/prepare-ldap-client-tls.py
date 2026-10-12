#!/usr/bin/env python3
"""Prepare the client TLS files required by DPS 0.9's LDAP configuration checks."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
from deployment_context import context_from_cli
ctx = context_from_cli()
import os, secrets, subprocess, yaml
os.umask(0o077)
B=ctx.runtime_root;C=B/'dps-install/config';L=C/'ldap';T=C/'tls'
key=L/'dps-client.key';crt=L/'dps-client.crt'
# Fresh LDAP may have its own signing CA; existing project-signed LDAP uses project CA.
CA=L/'tls/ca.crt'
CAKEY=L/'tls/ca.key' if (L/'tls/ca.key').exists() else T/'ca.key'
if not CA.is_file():raise SystemExit('LDAP trust CA is missing')
def openssl(*a):return subprocess.check_output(['openssl',*a],stderr=subprocess.PIPE)
if key.exists()!=crt.exists():
 raise SystemExit('Incomplete LDAP client TLS pair; restore missing material before rerunning')
if not key.exists() and (L/'dps-ldap-client-tls-secret.yaml').exists():
 raise SystemExit('Existing LDAP client identity is missing its certificate pair; restore rather than replace it')
if not key.exists():
 k=key.with_name('.dps-client.key.tmp');c=crt.with_name('.dps-client.crt.tmp')
 csr=L/'dps-client.csr';ext=L/'dps-client.ext'
 openssl('genrsa','-out',str(k),'3072')
 openssl('req','-new','-key',str(k),'-out',str(csr),'-subj','/CN=dps-ldap-client')
 ext.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\n')
 openssl('x509','-req','-in',str(csr),'-CA',str(CA),'-CAkey',str(CAKEY),
         '-set_serial',str(secrets.randbits(120) or 1),'-out',str(c),'-days','364','-sha256','-extfile',str(ext))
 k.replace(key);c.replace(crt)
key.chmod(0o600);crt.chmod(0o644)
assert openssl('pkey','-in',str(key),'-pubout')==openssl('x509','-in',str(crt),'-noout','-pubkey')
openssl('verify','-CAfile',str(CA),'-purpose','sslclient',str(crt))
openssl('x509','-in',str(crt),'-noout','-checkend','86400')
secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'dps-ldap-client-tls','namespace':ctx.settings['namespace']},
 'type':'kubernetes.io/tls','stringData':{'tls.crt':crt.read_text(),'tls.key':key.read_text(),'ca.crt':CA.read_text()}}
p=L/'dps-ldap-client-tls-secret.yaml';tmp=p.with_name('.'+p.name+'.tmp')
tmp.write_text(yaml.safe_dump(secret,sort_keys=False));tmp.chmod(0o600);tmp.replace(p)
print('Stable LDAP client TLS pair verified and Secret prepared; existing CA and other identities preserved.')
