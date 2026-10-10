#!/usr/bin/env python3
"""Prepare the independent OpenLDAP service without resetting existing directory data."""
import base64, hashlib, json, os, secrets, shutil, subprocess
from pathlib import Path
ROOT=Path('/raid/vince/deploy')
CFG=ROOT/'dps-install/config/ldap'
PKG=ROOT/'dps-install/packages/ldap'
DATA=ROOT/'dps-install/data/ldap'
IMAGE='dps-openldap:2.6.10-debian13'
IMAGE_ID='sha256:68b0ec36cc46324ce44dd357ec634dcd3264a5c078e3ff97e4878db7206a7eab'
BASE='dc=dps,dc=lab'
def run(args):
 return subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.decode()
def private(path, content):
 path.write_text(content);path.chmod(0o600)
def ssha(password):
 salt=secrets.token_bytes(16)
 return '{SSHA}'+base64.b64encode(hashlib.sha1(password.encode()+salt).digest()+salt).decode()
os.umask(0o077)
for d in (CFG, CFG/'tls', DATA, ROOT/'dps-install/data/ldap-backups'):
 d.mkdir(parents=True,exist_ok=True);d.chmod(0o700)
# Deployment must use the recorded image, never a mutable tag with different contents.
present=subprocess.run(['docker','image','inspect','--format','{{.Id}}',IMAGE],capture_output=True,text=True)
if present.returncode:
 archive=PKG/'openldap-2.6.10-runtime.tar'
 run(['docker','load','--input',str(archive)])
actual=run(['docker','image','inspect','--format','{{.Id}}',IMAGE]).strip()
if actual!=IMAGE_ID: raise SystemExit('LDAP runtime image identity differs from the fixed deployment version.')
credentials=CFG/'credentials.json'
if credentials.exists():
 info=json.loads(credentials.read_text())
 if info['base_dn']!=BASE or info['username']!='dps-lab':
  raise SystemExit('Existing LDAP identity differs; manual review required.')
else:
 if (DATA/'data.mdb').exists():
  raise SystemExit('Existing LDAP data without credentials; refusing to generate new passwords.')
 old=json.loads((ROOT/'dps-install/config/dps-access.json').read_text())
 if old['username']!='dps-lab' or len(old['password'])<24:
  raise SystemExit('Expected existing strong dps-lab credential.')
 info={
  'endpoint':'ldaps://10.6.131.43:1636','host':'10.6.131.43','port':1636,
  'dns':'ldap.dps.lab','base_dn':BASE,'user_base_dn':'ou=users,'+BASE,
  'group_base_dn':'ou=groups,'+BASE,'admin_dn':'cn=admin,'+BASE,
  'admin_password':secrets.token_urlsafe(36),
  'bind_dn':'uid=dps-bind,ou=services,'+BASE,'bind_password':secrets.token_urlsafe(36),
  'username':'dps-lab','user_dn':'uid=dps-lab,ou=users,'+BASE,'password':old['password'],
  'authorization_group':'dcpower-users','authorization_group_dn':'cn=dcpower-users,ou=groups,'+BASE,
  'noaccess_username':'dps-noaccess','noaccess_user_dn':'uid=dps-noaccess,ou=users,'+BASE,
  'noaccess_password':secrets.token_urlsafe(36)}
 private(credentials,json.dumps(info,indent=2)+'\n')
for name,key in (('admin.password','admin_password'),('bind.password','bind_password'),
                 ('user.password','password'),('noaccess.password','noaccess_password')):
 private(CFG/name,info[key])
tls=CFG/'tls'
key=tls/'server.key';cert=tls/'server.crt';ca=tls/'ca.crt'
if key.exists()!=cert.exists():raise SystemExit('LDAP TLS key/certificate pair incomplete; refusing replacement.')
project_ca=ROOT/'dps-install/config/tls/ca.crt'
if ca.exists() and ca.read_bytes()!=project_ca.read_bytes():
 raise SystemExit('Existing LDAP CA differs from project CA; manual review required.')
shutil.copyfile(project_ca,ca);ca.chmod(0o644)
ext=tls/'server.ext'
ext.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:ldap.dps.lab,DNS:localhost,IP:10.6.131.43,IP:127.0.0.1\n')
if not key.exists():
 run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',str(key)])
 run(['openssl','req','-new','-key',str(key),'-out',str(tls/'server.csr'),'-subj','/CN=ldap.dps.lab/O=DPS Lab'])
 run(['openssl','x509','-req','-in',str(tls/'server.csr'),'-CA',str(project_ca),
      '-CAkey',str(ROOT/'dps-install/config/tls/ca.key'),'-set_serial',str(secrets.randbits(128)),
      '-out',str(cert),'-days','825','-sha256','-extfile',str(ext)])
key.chmod(0o600);cert.chmod(0o644)
run(['openssl','verify','-CAfile',str(ca),'-purpose','sslserver','-verify_ip','10.6.131.43',str(cert)])
run(['openssl','verify','-CAfile',str(ca),'-purpose','sslserver','-verify_hostname','ldap.dps.lab',str(cert)])
run(['openssl','x509','-in',str(cert),'-noout','-checkend','86400'])
pub_cert=run(['openssl','x509','-in',str(cert),'-pubkey','-noout'])
pub_key=run(['openssl','pkey','-in',str(key),'-pubout'])
if pub_key!=pub_cert:raise SystemExit('LDAP key and certificate do not match.')
# Reusing hashes avoids needless configuration changes on repeated preparation.
hashfile=CFG/'password-hashes.json'
if hashfile.exists(): hashes=json.loads(hashfile.read_text())
else:
 hashes={k:ssha(info[k]) for k in ('admin_password','bind_password','password','noaccess_password')}
 private(hashfile,json.dumps(hashes,indent=2)+'\n')
conf=f"""include /etc/ldap/schema/core.schema
include /etc/ldap/schema/cosine.schema
include /etc/ldap/schema/nis.schema
include /etc/ldap/schema/inetorgperson.schema
pidfile /run/slapd/slapd.pid
argsfile /run/slapd/slapd.args
modulepath /usr/lib/ldap
moduleload back_mdb
TLSCACertificateFile /run/ldap-config/ca.crt
TLSCertificateFile /run/ldap-config/server.crt
TLSCertificateKeyFile /run/ldap-config/server.key
TLSProtocolMin 3.3
disallow bind_anon
require authc
security simple_bind=128
database mdb
maxsize 1073741824
suffix "{BASE}"
rootdn "{info['admin_dn']}"
rootpw {hashes['admin_password']}
directory /var/lib/ldap
index objectClass eq
index uid,cn eq
index member eq
# Authentication needs password comparison, but no account can read password hashes.
access to attrs=userPassword
 by anonymous auth
 by self auth
 by * none
# DPS service account can read directory entries but cannot modify any attribute.
access to *
 by dn.exact="{info['bind_dn']}" read
 by self read
 by * none
"""
private(CFG/'slapd.conf',conf)
seed=f"""dn: {BASE}
objectClass: top
objectClass: dcObject
objectClass: organization
dc: dps
o: DPS Independent Lab

dn: ou=users,{BASE}
objectClass: organizationalUnit
ou: users

dn: ou=groups,{BASE}
objectClass: organizationalUnit
ou: groups

dn: ou=services,{BASE}
objectClass: organizationalUnit
ou: services

dn: {info['bind_dn']}
objectClass: account
objectClass: simpleSecurityObject
uid: dps-bind
userPassword: {hashes['bind_password']}

dn: {info['user_dn']}
objectClass: inetOrgPerson
objectClass: posixAccount
uid: dps-lab
cn: DPS Lab Administrator
sn: Administrator
uidNumber: 10000
gidNumber: 10000
homeDirectory: /nonexistent
loginShell: /usr/sbin/nologin
userPassword: {hashes['password']}

dn: {info['noaccess_user_dn']}
objectClass: inetOrgPerson
objectClass: posixAccount
uid: dps-noaccess
cn: DPS Unprivileged Verification User
sn: Verification
uidNumber: 10002
gidNumber: 10000
homeDirectory: /nonexistent
loginShell: /usr/sbin/nologin
userPassword: {hashes['noaccess_password']}

dn: {info['authorization_group_dn']}
objectClass: groupOfNames
cn: dcpower-users
member: {info['user_dn']}

"""
private(CFG/'bootstrap.ldif',seed)
compose=f"""services:
  openldap:
    image: {IMAGE_ID}
    container_name: dps-openldap
    restart: unless-stopped
    read_only: true
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - FOWNER
      - SETUID
      - SETGID
      - DAC_OVERRIDE
    ports:
      - "10.6.131.43:1636:1636"
    volumes:
      - {CFG}:/ldap/config:ro
      - {DATA}:/var/lib/ldap
    tmpfs:
      - /run:rw,nosuid,nodev,mode=755
      - /tmp:rw,nosuid,nodev,mode=1777
    environment:
      LDAPTLS_CACERT: /ldap/config/tls/ca.crt
      LDAPTLS_REQCERT: demand
    healthcheck:
      test: ["CMD", "ldapwhoami", "-x", "-H", "ldaps://127.0.0.1:1636", "-D", "{info['bind_dn']}", "-y", "/ldap/config/bind.password"]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 10s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
"""
private(CFG/'compose.yaml',compose)
manifest={
 'image':IMAGE,'image_id':IMAGE_ID,
 'base_image':'debian:trixie-20261005-slim',
 'base_digest':'sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f',
 'packages':{'slapd':'2.6.10+dfsg-1','ldap-utils':'2.6.10+dfsg-1','openssl':'3.5.7-1~deb13u3','ca-certificates':'20250419'},
 'archive':str(PKG/'openldap-2.6.10-runtime.tar'),
 'archive_sha256':hashlib.sha256((PKG/'openldap-2.6.10-runtime.tar').read_bytes()).hexdigest(),
 'endpoint':info['endpoint'],'base_dn':BASE,
 'user_base_dn':info['user_base_dn'],'group_base_dn':info['group_base_dn'],
 'bind_dn':info['bind_dn'],'user_dn':info['user_dn'],'authorization_group':info['authorization_group'],
 'ca_path':str(ca),'data_path':str(DATA),
 'sources':['https://openldap.org/doc/admin26/tls.html','https://openldap.org/doc/admin26/security.html',
            'https://packages.debian.org/trixie/slapd','https://hub.docker.com/_/debian/']}
private(CFG/'deployment.json',json.dumps(manifest,indent=2)+'\n')
for filename,name,values in (
 ('dps-ldap-bind-secret.yaml','dps-ldap-bind',{'bind-password':info['bind_password'].encode()}),
 ('dps-ldap-ca-secret.yaml','dps-ldap-ca',{'ca.crt':ca.read_bytes()})):
 secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':'dps'},
         'type':'Opaque','data':{k:base64.b64encode(v).decode() for k,v in values.items()}}
 private(CFG/filename,json.dumps(secret,indent=2)+'\n')
print('OpenLDAP configuration prepared; credentials and database retained.')
print('Endpoint: '+info['endpoint'])
