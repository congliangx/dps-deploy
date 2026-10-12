#!/usr/bin/env python3
"""Prepare the independent LDAP integration and preserve existing JWT identities."""
import sys
sys.dont_write_bytecode = True
import hashlib, json, os, subprocess
from datetime import datetime
from pathlib import Path
from deployment_context import context_from_cli
ctx = context_from_cli()
from zoneinfo import ZoneInfo
import yaml
os.umask(0o077)
B = ctx.runtime_root
C = B/'dps-install/config'
V, S = C/'values.yaml', C/'ldap-auth-migration.json'
def save(path, value, json_format=False):
    tmp = path.with_name('.'+path.name+'.tmp')
    tmp.write_text(json.dumps(value, indent=2)+'\n' if json_format else yaml.safe_dump(value, sort_keys=False))
    tmp.chmod(0o600)
    tmp.replace(path)
def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
def public_sha(path):
    pub = subprocess.check_output(['openssl','pkey','-in',str(path),'-pubout','-outform','DER'], stderr=subprocess.PIPE)
    return hashlib.sha256(pub).hexdigest()
subprocess.run([str(ctx.source_path('dps-install/scripts/ldap-status.sh'))], check=True)
ldap = json.loads((C/'ldap/credentials.json').read_text())
account = json.loads((C/'dps-access.json').read_text())
assert ldap['username'] == account['username'] == 'dps-lab'
assert ldap['password'] == account['password'], 'LDAP and documented user credentials differ'
assert ldap['endpoint'] == f"ldaps://{ctx.settings['host_ip']}:{ctx.settings['ldap_port']}"
assert ldap['bind_dn'] == 'uid=dps-bind,ou=services,dc=dps,dc=lab'
for filename, name, key in [
    ('dps-ldap-bind-secret.yaml','dps-ldap-bind','bind-password'),
    ('dps-ldap-ca-secret.yaml','dps-ldap-ca','ca.crt')]:
    secret = yaml.safe_load((C/'ldap'/filename).read_text())
    assert secret['metadata']['name'] == name and secret['metadata']['namespace'] == ctx.settings['namespace']
    assert key in secret.get('stringData',{}) or key in secret.get('data',{})
values = yaml.safe_load(V.read_text())
auth = values['dps'].setdefault('auth',{})
state = json.loads(S.read_text()) if S.exists() else {
    'started_at':now(), 'original_authenticator':auth.get('authenticatorType'),
    'target_authenticator':'ldap'}
key = C/'tls/jwt-private-key.pem'
rotation = state.get('jwt_rotation')
current = public_sha(key)
if rotation:
    if rotation.get('status') not in ('committed', 'retained') or current != rotation.get('new_public_key_sha256'):
        raise SystemExit('JWT identity differs from its retained record; restore/review rather than rotate')
else:
    if auth.get('authenticatorType') != 'ldap':
        raise SystemExit('Maintenance requires an existing LDAP identity; use fresh preparation for a new instance')
    rotation = {'new_public_key_sha256':current, 'status':'retained', 'recorded_at':now()}
    state['jwt_rotation'] = rotation
key.chmod(0o600)
auth['authenticatorType']='ldap'
auth['auth_required_groups']='dcpower-users'
auth.setdefault('oidc',{})['enabled']=False
auth['jwt']={'existingSecret':'dps-jwt-keys','existingSecretKey':'private-key.pem'}
subprocess.run(['python3',str(ctx.source_path('dps-install/scripts/prepare-ldap-client-tls.py'))],check=True)
values['dps']['ldap'] = {
    'enabled':True, 'serverUrl':ldap['endpoint'], 'bindDn':ldap['bind_dn'],
    'baseDn':ldap['base_dn'],
    'userFilter':'(&(objectClass=person)(uid={username}))',
    'groupProfile':'groupOfNames',
    'groupFilter':'(&(objectClass=groupOfNames)(member={userdn}))',
    'groupAttribute':'cn', 'defaultRole':'',
    'groupRoleMapping':'dcpower-users=admin',
    'bindPassword':{'existingSecret':'dps-ldap-bind','existingSecretKey':'bind-password','mountSecret':True},
    'certSource':'file','tlsCaCert':'/secrets/ldap/ca.crt',
    'tlsClientCert':'/secrets/ldap/tls.crt','tlsClientKey':'/secrets/ldap/tls.key',
    'volumeMounts':[{'name':'ldap-certs','mountPath':'/secrets/ldap','readOnly':True}],
    'volumes':[{'name':'ldap-certs','projected':{'sources':[{'secret':{'name':'dps-ldap-ca','items':[{'key':'ca.crt','path':'ca.crt'}]}},{'secret':{'name':'dps-ldap-client-tls','items':[{'key':'tls.crt','path':'tls.crt'},{'key':'tls.key','path':'tls.key'}]}}]}}]
}
save(V,values)
account.update({'authenticator':'ldap','authentication':'ldap','role':'admin','ldap_dn':ldap['user_dn'],'note':'Real LDAP user; password is verified by the independent OpenLDAP service, admin role comes from dcpower-users.'})
account.pop('authentication_note',None)
save(C/'dps-access.json',account,True)
subprocess.run(['python3',str(ctx.source_path('dps-install/scripts/prepare-certificates.py'))],check=True)
state['status']='configured'
state['configured_at']=now()
state['ldap_endpoint']=ldap['endpoint']
state['bind_secret']='dps-ldap-bind'
state['ca_secret']='dps-ldap-ca'
state['jwt_secret']='dps-jwt-keys'
save(S,state,True)
print('LDAP values and external Secrets prepared. Existing JWT signing identity preserved; no password printed.')
print('Next: prepare-namespace.sh, then install-dps.sh to apply the reviewed Helm configuration.')
