#!/usr/bin/env python3
"""Verify the standalone LDAP service; secrets stay out of arguments and reports."""

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
import datetime, json, secrets, subprocess
from pathlib import Path
ROOT=CTX.runtime_root
CFG=ROOT/'dps-install/config/ldap'
info=json.loads((CFG/'credentials.json').read_text())
endpoint=info['endpoint']
checks=[]
def record(name,passed,detail):
 checks.append({'name':name,'passed':bool(passed),'detail':detail})
 print(name+': '+('PASS' if passed else 'FAIL'))
def ldap(tool,args=[],password=None,dn=None,extraenv=[]):
 command=['docker','exec','-i']
 for e in extraenv: command+=['-e',e]
 command+=[SETTINGS['ldap_container'],tool,'-x','-H',endpoint]
 if dn:command+=['-D',dn]
 if password is not None:command+=['-y','/dev/stdin']
 command+=args
 return subprocess.run(command,input=password or '',capture_output=True,text=True,timeout=20)
def bind(name,dn,key,expected=0):
 r=ldap('ldapwhoami',password=info[key],dn=dn)
 record(name,r.returncode==expected,{'returncode':r.returncode,'expected':expected})
 return r
bind('service-bind',info['bind_dn'],'bind_password')
bind('admin-bind',info['admin_dn'],'admin_password')
bind('authorized-user-bind',info['user_dn'],'password')
bind('unprivileged-user-bind',info['noaccess_user_dn'],'noaccess_password')
wrong=secrets.token_urlsafe(24)
for name,dn in [('wrong-user-password',info['user_dn']),
                ('nonexistent-user','uid=dps-missing,ou=users,'+info['base_dn']),
                ('wrong-service-password',info['bind_dn'])]:
 r=ldap('ldapwhoami',password=wrong,dn=dn)
 record(name,r.returncode==49,{'returncode':r.returncode,'expected':49})
r=ldap('ldapwhoami',password='',dn=info['user_dn'])
record('empty-password-rejected',r.returncode!=0,{'returncode':r.returncode})
r=ldap('ldapsearch',['-LLL','-b',info['base_dn'],'(uid='+info['username']+')','uid'])
record('anonymous-directory-denied',r.returncode!=0,{'returncode':r.returncode})
user_filter='(&(objectClass=person)(uid='+info['username']+'))'
r=ldap('ldapsearch',['-LLL','-b',info['user_base_dn'],user_filter,'uid','cn'],
       password=info['bind_password'],dn=info['bind_dn'])
record('service-user-search',r.returncode==0 and 'dn: '+info['user_dn'] in r.stdout,
       {'returncode':r.returncode,'user_dn':info['user_dn'],'filter':user_filter})
group_filter='(&(objectClass=groupOfNames)(member='+info['user_dn']+'))'
r=ldap('ldapsearch',['-LLL','-b',info['group_base_dn'],group_filter,'cn','member'],
       password=info['bind_password'],dn=info['bind_dn'])
record('authorized-group-membership',r.returncode==0 and 'cn: '+info['authorization_group'] in r.stdout
       and info['user_dn'] in r.stdout,{'returncode':r.returncode,'group':info['authorization_group']})
r=ldap('ldapsearch',['-LLL','-b',info['group_base_dn'],
       '(&(objectClass=groupOfNames)(member='+info['noaccess_user_dn']+'))','cn'],
       password=info['bind_password'],dn=info['bind_dn'])
record('unprivileged-user-not-authorized',r.returncode==0 and 'cn: '+info['authorization_group'] not in r.stdout,
       {'returncode':r.returncode,'user':info['noaccess_username']})
r=ldap('ldapsearch',['-LLL','-b',info['user_dn'],'-s','base','(objectClass=*)','userPassword'],
       password=info['bind_password'],dn=info['bind_dn'])
record('service-cannot-read-password',r.returncode==0 and 'userPassword:' not in r.stdout,
       {'returncode':r.returncode,'attribute_returned':'userPassword:' in r.stdout})
modify='dn: '+info['user_dn']+'\nchangetype: modify\nreplace: description\ndescription: service-bind-must-not-write\n\n'
r=subprocess.run(['docker','exec','-i',SETTINGS['ldap_container'],'ldapmodify','-x','-H',endpoint,
                  '-D',info['bind_dn'],'-y','/ldap/config/bind.password'],
                 input=modify,capture_output=True,text=True,timeout=20)
record('service-cannot-modify-directory',r.returncode==50,{'returncode':r.returncode,'expected':50})
if r.returncode==0:
 clean='dn: '+info['user_dn']+'\nchangetype: modify\ndelete: description\n\n'
 subprocess.run(['docker','exec','-i',SETTINGS['ldap_container'],'ldapmodify','-x','-H',endpoint,
                 '-D',info['admin_dn'],'-y','/ldap/config/admin.password'],
                 input=clean,capture_output=True,text=True,check=True)
r=ldap('ldapwhoami',password=info['bind_password'],dn=info['bind_dn'],
       extraenv=['LDAPTLS_CACERT=/etc/ssl/certs/ca-certificates.crt','LDAPTLS_REQCERT=demand'])
record('untrusted-ca-rejected',r.returncode!=0,{'returncode':r.returncode})
r=subprocess.run(['docker','exec','-i',SETTINGS['ldap_container'],'openssl','s_client',
                  '-connect',f"{SETTINGS['host_ip']}:{SETTINGS['ldap_port']}",'-CAfile','/ldap/config/tls/ca.crt',
                  '-verify_return_error','-verify_hostname','wrong.'+info['dns']],
                 input='',capture_output=True,text=True,timeout=20)
record('incorrect-server-name-rejected',r.returncode!=0 and 'hostname mismatch' in r.stderr.lower(),
       {'returncode':r.returncode,'hostname_mismatch':'hostname mismatch' in r.stderr.lower()})
r=subprocess.run(['docker','exec','-i',SETTINGS['ldap_container'],'openssl','s_client',
                  '-connect',f"{SETTINGS['host_ip']}:{SETTINGS['ldap_port']}",'-CAfile','/ldap/config/tls/ca.crt',
                  '-verify_return_error','-verify_hostname',info['dns']],
                 input='',capture_output=True,text=True,timeout=20)
record('ldap-dns-certificate-verified',r.returncode==0 and 'Verification: OK' in r.stdout,
       {'returncode':r.returncode,'hostname':info['dns']})
meta=subprocess.run(['docker','inspect','--format',
                     '{{.State.Health.Status}} {{.HostConfig.RestartPolicy.Name}}',
                     SETTINGS['ldap_container']],capture_output=True,text=True,check=True).stdout.strip()
record('healthy-auto-restart',meta=='healthy unless-stopped',{'state':meta})
version=subprocess.run(['docker','exec',SETTINGS['ldap_container'],'slapd','-VV'],
                       capture_output=True,text=True).stderr.splitlines()[0]
report={'timestamp':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
        'endpoint':endpoint,'base_dn':info['base_dn'],'version':version,
        'passed':all(c['passed'] for c in checks),'passed_count':sum(c['passed'] for c in checks),
        'total_count':len(checks),'checks':checks}
out=ROOT/'verification/reports/ldap-installation.json'
out.write_text(json.dumps(report,indent=2)+'\n');out.chmod(0o600)
print('LDAP verification: %s/%s passed'%(report['passed_count'],report['total_count']))
raise SystemExit(0 if report['passed'] else 1)
