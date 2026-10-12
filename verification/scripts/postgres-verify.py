#!/usr/bin/env python3
"""Read secrets from mounted files inside a disposable client; print no passwords."""

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
from pathlib import Path
import subprocess, json, datetime, os
root=CTX.runtime_root
cfg=root/'dps-install/config/postgresql'
image=json.loads(subprocess.check_output(['docker','inspect',SETTINGS['pg_container'],'--format','{{json .Config.Image}}'],text=True))
def run(sql, sslmode='verify-full', wrong_password=False):
    env="export PGPASSWORD=invalid-verification-password;" if wrong_password else "export PGPASSWORD=\"$(cat /run/secrets/dps-password)\";"
    cmd=env+" export PGSSLMODE="+sslmode+" PGSSLROOTCERT=/run/postgresql-ca.crt; exec psql -X -v ON_ERROR_STOP=1 -At -h "+SETTINGS["host_ip"]+" -p "+str(SETTINGS["pg_port"])+" -U dps -d dps"
    return subprocess.run([
        'docker','run','--rm','-i','--network','host','--entrypoint','sh',
        '-v',str(cfg/'secrets/dps-password')+':/run/secrets/dps-password:ro',
        '-v',str(cfg/'tls/ca.crt')+':/run/postgresql-ca.crt:ro',
        image,'-c',cmd],input=sql,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
sql="""
SELECT json_build_object('server_version',current_setting('server_version'),'database',current_database(),'current_user',current_user,'role_superuser',(SELECT rolsuper FROM pg_roles WHERE rolname=current_user),'role_createdb',(SELECT rolcreatedb FROM pg_roles WHERE rolname=current_user),'role_createrole',(SELECT rolcreaterole FROM pg_roles WHERE rolname=current_user),'ssl',ssl,'tls_version',version,'cipher',cipher) FROM pg_stat_ssl WHERE pid=pg_backend_pid();
BEGIN;
CREATE SCHEMA prereq_verification_schema;
CREATE TABLE prereq_verification_schema.migration_check(id integer primary key);
INSERT INTO prereq_verification_schema.migration_check VALUES(1);
SELECT 'migration_check_rows='||count(*) FROM prereq_verification_schema.migration_check;
DROP SCHEMA prereq_verification_schema CASCADE;
ROLLBACK;
"""
ok=run(sql)
no_tls=run('SELECT 1;',sslmode='disable')
bad_password=run('SELECT 1;',wrong_password=True)
details={}
if ok.returncode==0:
    details=json.loads(ok.stdout.splitlines()[0])
admin=subprocess.run(['docker','exec','-u','postgres',SETTINGS['pg_container'],'psql','-X','-At','-v','ON_ERROR_STOP=1','-U','postgres','-d','dps','-c',
    "SELECT json_build_object('owner',pg_get_userbyid(datdba),'dps_password_scram',(SELECT rolpassword LIKE 'SCRAM-SHA-256$%' FROM pg_authid WHERE rolname='dps'),'max_connections',current_setting('max_connections')) FROM pg_database WHERE datname='dps';"],text=True,capture_output=True)
report={'generated_at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
'image':image,'endpoint':f"{SETTINGS['host_ip']}:{SETTINGS['pg_port']}",'authenticated_sql_ok':ok.returncode==0,'connection':details,
'migration_ddl_transaction_ok':ok.returncode==0 and 'migration_check_rows=1' in ok.stdout,
'non_tls_rejected':no_tls.returncode!=0,'wrong_password_rejected':bad_password.returncode!=0,
'admin_metadata':json.loads(admin.stdout) if admin.returncode==0 else {},
'kubernetes_pod_path':'pending parent cluster verification','dps_application_migration':'not run; DPS not installed'}
(root/'verification/reports/postgres-host-verification.json').write_text(json.dumps(report,indent=2)+'\n')
log={'positive_stdout':ok.stdout,'positive_stderr':ok.stderr,'non_tls_stderr':no_tls.stderr,'wrong_password_stderr':bad_password.stderr}
(root/'verification/logs/postgres-host-verification.log').write_text(json.dumps(log,indent=2)+'\n')
print(json.dumps(report,indent=2))
if not all(report[k] for k in ['authenticated_sql_ok','migration_ddl_transaction_ok','non_tls_rejected','wrong_password_rejected']):
    raise SystemExit(1)
