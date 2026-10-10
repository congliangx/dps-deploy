#!/usr/bin/env python3
"""Create only the PRS databases and narrowly scoped TLS/SCRAM HBA rules."""
import datetime, json, os, subprocess
from pathlib import Path
ROOT=Path('/raid/vince/deploy')
CFG=ROOT/'dps-install/config/prs'
HBA=ROOT/'dps-install/config/postgresql/pg_hba.conf'
BACKUPS=ROOT/'dps-install/data/postgresql-backups'
DBS=['dps_prs_config','dps_prs_config_staged','dps_prs_controller']
NETWORKS=['10.6.131.43/32','10.42.0.0/16','172.30.90.0/24']
def admin(sql,database='postgres'):
 r=subprocess.run(['docker','exec','-i','-u','postgres','dps-postgresql',
                   'psql','-X','-v','ON_ERROR_STOP=1','-At','-d',database],
                   input=sql,capture_output=True,text=True,check=True)
 return r.stdout.strip()
def replace_in_place(text):
 # This file is bind-mounted individually. Preserve its inode so PostgreSQL sees it.
 with HBA.open('w') as f:
  f.write(text);f.flush();os.fsync(f.fileno())
os.umask(0o077)
BACKUPS.mkdir(parents=True,exist_ok=True)
CFG.mkdir(parents=True,exist_ok=True)
current=admin("SELECT datname || '|' || pg_get_userbyid(datdba) FROM pg_database ORDER BY datname;")
ownership=dict(row.split('|',1) for row in current.splitlines())
for name in DBS:
 if name in ownership and ownership[name]!='dps':
  raise SystemExit('Existing PRS database belongs to another role: '+name)
old=HBA.read_text()
for net in NETWORKS:
 if f'hostssl dps dps {net} scram-sha-256' not in old:
  raise SystemExit('Existing narrowly scoped DPS TLS rule missing for '+net)
if 'hostnossl all all 0.0.0.0/0 reject' not in old or 'hostnossl all all ::/0 reject' not in old:
 raise SystemExit('Existing plaintext rejection rules missing; review HBA before preparation.')
start='# BEGIN DPS PRS TLS DATABASES\n'
end='# END DPS PRS TLS DATABASES\n'
block=start+'# PRS uses the same non-superuser role and trusted client networks.\n'
for net in NETWORKS:
 block+='hostssl '+','.join(DBS)+' dps '+net+' scram-sha-256\n'
block+=end
if start in old:
 a=old.index(start);b=old.index(end,a)+len(end)
 new=old[:a]+block+old[b:]
else:
 anchor='host all all 0.0.0.0/0 reject'
 if anchor not in old:raise SystemExit('Final reject rule missing; refusing to append after unknown HBA rules.')
 new=old.replace(anchor,block+anchor,1)
new=new.replace('# PostgreSQL authentication; only dps database/role can connect over TLS.', '# PostgreSQL authentication; DPS and PRS databases use role dps over TLS only.')
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
if new!=old or any(n not in ownership for n in DBS):
 # Preserve the live DPS application database before extending the shared server.
 subprocess.run([str(ROOT/'dps-install/scripts/postgresql-backup.sh')],check=True)
 for name in DBS:
  if name in ownership:
   dest=BACKUPS/f'{name}-before-prs-{stamp}.dump'
   with dest.open('wb') as f:
    subprocess.run(['docker','exec','-u','postgres','dps-postgresql',
                    'pg_dump','-U','postgres','-d',name,'--format=custom'],stdout=f,check=True)
   with dest.open('rb') as f:
    subprocess.run(['docker','exec','-i','-u','postgres','dps-postgresql',
                    'pg_restore','--list'],stdin=f,stdout=subprocess.DEVNULL,check=True)
sql=(CFG/'prepare-databases.sql').read_text()
admin(sql)
hba_backup=None
if new!=old:
 hba_backup=BACKUPS/f'pg_hba-before-prs-{stamp}.conf'
 hba_backup.write_text(old);hba_backup.chmod(0o600)
 try:
  replace_in_place(new)
  errors=admin('SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL;')
  if errors!='0':raise RuntimeError('Invalid new HBA rules; restoring previous file.')
  if admin('SELECT pg_reload_conf();')!='t':raise RuntimeError('PostgreSQL rejected configuration reload.')
 except Exception:
  replace_in_place(old)
  admin('SELECT pg_reload_conf();')
  raise
for name in DBS:
 if admin("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='"+name+"';")!='dps':
  raise SystemExit('PRS database ownership check failed: '+name)
 checks=admin("SELECT has_database_privilege('dps',current_database(),'CONNECT') AND "
              "has_schema_privilege('dps','public','USAGE') AND "
              "has_schema_privilege('dps','public','CREATE');",name)
 if checks!='t':raise SystemExit('PRS migration privileges missing: '+name)
previous_manifest=CFG/'databases.json'
previous=json.loads(previous_manifest.read_text()) if previous_manifest.exists() else {}
manifest={
 'postgresql_endpoint':'10.6.131.43:15432','username':'dps','database_names':DBS,
 'tls_required':True,'password_authentication':'scram-sha-256','allowed_client_networks':NETWORKS,
 'hba_path':str(HBA),'hba_previous_backup':str(hba_backup) if hba_backup else previous.get('hba_previous_backup'),
 'prepare_sql':str(CFG/'prepare-databases.sql'),'database_extensions_precreated':[],
 'dps_database_preserved':True,
 'power_steering_chart_version':'2.1.0',
 'client_tls_environment':{'PGSSLMODE':'verify-full','PGSSLROOTCERT':'/secrets/postgresql/ca.crt'},
 'client_tls_source':'power-config 2.1.0 SQLAlchemy/psycopg2/libpq environment defaults'}
out=CFG/'databases.json';out.write_text(json.dumps(manifest,indent=2)+'\n');out.chmod(0o600)
print('PRS databases prepared: '+', '.join(DBS))
print('Owner dps; PostgreSQL remains TLS/SCRAM-only on existing trusted client networks.')
print('Existing DPS database retained; PostgreSQL configuration reloaded without server restart.')
