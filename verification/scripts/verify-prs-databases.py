#!/usr/bin/env python3
"""Verify PRS databases using the pinned application's actual SQLAlchemy engine."""
import datetime,json,subprocess
from pathlib import Path
ROOT=Path('/raid/vince/deploy')
DBS=['dps_prs_config','dps_prs_config_staged','dps_prs_controller']
checks=[]
def record(name,passed,detail):
 checks.append({'name':name,'passed':bool(passed),'detail':detail})
 print(name+': '+('PASS' if passed else 'FAIL'))
def admin(sql,database='postgres'):
 return subprocess.run(['docker','exec','-i','-u','postgres','dps-postgresql','psql','-X','-At',
                        '-v','ON_ERROR_STOP=1','-d',database],
                       input=sql,capture_output=True,text=True,check=True).stdout.strip()
payload=r"""
import json,os,secrets
from pathlib import Path
from sqlalchemy import URL,text
from config.db.database import EngineFactory
import psycopg2
password=Path('/run/secrets/dps-password').read_text().strip()
databases=['dps_prs_config','dps_prs_config_staged','dps_prs_controller']
positive=[]
os.environ['PGSSLMODE']='verify-full'
os.environ['PGSSLROOTCERT']='/secrets/postgresql/ca.crt'
for name in databases:
 uri=URL.create('postgresql',username='dps',password=password,host='10.6.131.43',port=15432,database=name)
 engine=EngineFactory.create(uri.render_as_string(hide_password=False))
 with engine.connect() as conn:
  row=conn.execute(text("SELECT current_database(),current_user,s.ssl,s.version FROM pg_stat_ssl s WHERE s.pid=pg_backend_pid()")).one()
  table='prs_prerequisite_'+secrets.token_hex(6)
  conn.exec_driver_sql('CREATE TABLE public.'+table+' (id integer PRIMARY KEY)')
  conn.exec_driver_sql('INSERT INTO public.'+table+' VALUES (1)')
  count=conn.exec_driver_sql('SELECT count(*) FROM public.'+table).scalar()
  conn.rollback()
 positive.append({'database':row[0],'username':row[1],'tls':row[2],'tls_protocol':row[3],'transactional_ddl_insert_rollback':count==1})
 engine.dispose()
negative=[]
cases=[
 ('untrusted-ca','verify-full','/secrets/postgresql/untrusted-ca.crt','10.6.131.43',password,None,'certificate verify failed'),
 ('incorrect-server-name','verify-full','/secrets/postgresql/ca.crt','untrusted.dps.lab',password,'10.6.131.43','does not match host name'),
 ('plaintext-rejected','disable','/secrets/postgresql/ca.crt','10.6.131.43',password,None,'no encryption'),
 ('wrong-password-rejected','verify-full','/secrets/postgresql/ca.crt','10.6.131.43',secrets.token_urlsafe(32),None,'password authentication failed')]
for label,mode,ca,host,pw,addr,expected in cases:
 os.environ['PGSSLMODE']=mode;os.environ['PGSSLROOTCERT']=ca
 if addr:os.environ['PGHOSTADDR']=addr
 else:os.environ.pop('PGHOSTADDR',None)
 uri=URL.create('postgresql',username='dps',password=pw,host=host,port=15432,database='dps_prs_config')
 engine=EngineFactory.create(uri.render_as_string(hide_password=False))
 try:
  with engine.connect() as conn:conn.execute(text('SELECT 1'))
  negative.append({'name':label,'passed':False,'failure_category':'unexpected-success'})
 except Exception as exc:
  negative.append({'name':label,'passed':expected in str(exc).lower(),'failure_category':label,
                   'exception_type':type(exc).__name__})
 finally:engine.dispose()
print(json.dumps({'client':'power-config EngineFactory SQLAlchemy/psycopg2','driver_version':psycopg2.__version__,
                  'positive':positive,'negative':negative}))
"""
command=['docker','run','--rm','--network=host','--read-only','--user=0','--entrypoint','python3',
         '-e','PGCONNECT_TIMEOUT=10',
         '-v',str(ROOT/'dps-install/config/postgresql/secrets/dps-password')+':/run/secrets/dps-password:ro',
         '-v',str(ROOT/'dps-install/config/postgresql/tls/ca.crt')+':/secrets/postgresql/ca.crt:ro',
         '-v',str(ROOT/'dps-install/config/tls/ca.crt')+':/secrets/postgresql/untrusted-ca.crt:ro',
         'nvcr.io/nvidia/power-config:2.1.0','-c',payload]
r=subprocess.run(command,capture_output=True,text=True,timeout=60,check=True)
result=json.loads(r.stdout)
for row in result['positive']:
 record('config-engine-'+row['database'],row['tls'] and row['username']=='dps' and row['transactional_ddl_insert_rollback'],row)
for row in result['negative']:
 record(row['name'],row['passed'],{k:v for k,v in row.items() if k not in ('name','passed')})
controller_payload=r"""
import json,os
from pathlib import Path
from sqlalchemy import URL,text
from controller.db.database import EngineFactory
import psycopg2
from prs_shared.settings import DatabaseSettings
os.environ['PGSSLMODE']='verify-full'
os.environ['PGSSLROOTCERT']='/secrets/postgresql/ca.crt'
password=Path('/run/secrets/dps-password').read_text().strip()
uri=URL.create('postgresql',username='dps',password=password,host='10.6.131.43',port=15432,database='dps_prs_controller')
engine=EngineFactory.create(uri.render_as_string(hide_password=False))
with engine.connect() as conn:
 row=conn.execute(text("SELECT current_database(),current_user,s.ssl,s.version FROM pg_stat_ssl s WHERE s.pid=pg_backend_pid()")).one()
 conn.rollback()
engine.dispose()
print(json.dumps({'database':row[0],'username':row[1],'tls':row[2],'tls_protocol':row[3],
                  'driver_version':psycopg2.__version__,'database_setting_fields':list(DatabaseSettings.model_fields)}))
"""
controller_command=command[:]
controller_command[-3]='nvcr.io/nvidia/power-controller:2.1.0'
controller_command[-1]=controller_payload
r=subprocess.run(controller_command,capture_output=True,text=True,timeout=60,check=True)
controller=json.loads(r.stdout)
record('controller-engine-tls',controller['tls'] and controller['username']=='dps',controller)
for name in DBS:
 row=admin("SELECT pg_get_userbyid(datdba),has_database_privilege('dps',datname,'CONNECT') "
           "FROM pg_database WHERE datname='"+name+"';")
 schema=admin("SELECT has_schema_privilege('dps','public','USAGE') AND has_schema_privilege('dps','public','CREATE');",name)
 record('owner-and-migration-privileges-'+name,row=='dps|t' and schema=='t',{'database':name,'owner_and_connect':row,'schema_migration_privileges':schema})
 leftovers=admin("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'prs_prerequisite_%';",name)
 record('probe-rollback-'+name,leftovers=='0',{'leftover_tables':int(leftovers)})
role=admin("SELECT rolsuper,rolcreatedb,rolcreaterole,(rolpassword LIKE 'SCRAM-SHA-256$%') FROM pg_authid WHERE rolname='dps';")
record('non-superuser-scram-role',role=='f|f|f|t',{'superuser_createdb_createrole_scram_flags':role})
errors=admin("SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL;")
record('hba-rules-valid',errors=='0',{'errors':int(errors)})
rules=admin("SELECT count(*) FROM pg_hba_file_rules WHERE type='hostssl' AND user_name=ARRAY['dps'] "
            "AND database=ARRAY['dps_prs_config','dps_prs_config_staged','dps_prs_controller'] "
            "AND auth_method='scram-sha-256';")
record('three-trusted-network-prs-rules',rules=='3',{'scoped_hostssl_rules':int(rules)})
tables=admin("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';",'dps')
record('existing-dps-database-present',int(tables)>0,{'public_table_count':int(tables)})
report={'timestamp':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
        'passed':all(c['passed'] for c in checks),'passed_count':sum(c['passed'] for c in checks),
        'total_count':len(checks),'database_names':DBS,
        'client_tls_environment':{'PGSSLMODE':'verify-full','PGSSLROOTCERT':'/secrets/postgresql/ca.crt'},
        'checks':checks,
        'limitations':['Client probes run in independent application image containers using host networking. Live Pod sessions are verified after Helm deployment.']}
out=ROOT/'verification/reports/prs-databases.json'
out.write_text(json.dumps(report,indent=2)+'\n');out.chmod(0o600)
print('PRS database verification: %s/%s passed'%(report['passed_count'],report['total_count']))
raise SystemExit(0 if report['passed'] else 1)
