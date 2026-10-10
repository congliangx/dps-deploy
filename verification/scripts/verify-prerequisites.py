#!/usr/bin/env python3
"""Verify DPS prerequisites using temporary resources; never install DPS or write BMC power."""
import base64,datetime,hashlib,json,os,pathlib,re,subprocess,sys,time,uuid
import yaml
BASE=pathlib.Path('/raid/vince/deploy')
# source dps-install/config/dps-env.sh to override these project defaults.
CONTEXT=os.environ.get('DPS_KUBE_CONTEXT','dps-l20-12')
TARGET_NODE=os.environ.get('DPS_KUBE_NODE','l20-12')
NAMESPACE='dps'
KUBECONFIG=pathlib.Path(os.environ.get('KUBECONFIG',str(BASE/'dps-install/config/kubernetes/kubeconfig.yaml')))
ENV=dict(os.environ,KUBECONFIG=str(KUBECONFIG))
REPORT=BASE/'verification/reports/prerequisite-check.json'
LOGDIR=BASE/'verification/logs'
MANIFESTDIR=BASE/'verification/manifests'
for directory in [REPORT.parent,LOGDIR,MANIFESTDIR]:directory.mkdir(parents=True,exist_ok=True)
report={'checked_at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'context':CONTEXT,'namespace':NAMESPACE,'scope':'Prerequisites only; no DPS release or topology import; BMC requests GET only','status':'running','checks':{},'temporary_resources':{},'limitations':['DPS migration/startup and API/UI authentication remain unverified until a later DPS installation.']}
def command(args,check=True):
    result=subprocess.run(args,env=ENV,text=True,capture_output=True)
    if check and result.returncode:raise RuntimeError('Command failed: '+args[0]+' '+str(result.returncode)+' '+result.stderr[:600])
    return result

def kubectl(*args,check=True):return command(['kubectl','--context',CONTEXT,*args],check)
def kubejson(*args):return json.loads(kubectl(*args,'-o','json').stdout)
def save():REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
def condition(check,name,details):
    report['checks'][name]={'passed':bool(check),'details':details};save()
    if not check:raise RuntimeError('Failed prerequisite: '+name)
def decode(secret,key):return base64.b64decode(secret['data'][key])
PYTHON_CODE=r"""
import base64,concurrent.futures,json,pathlib,socket,ssl,urllib.request,uuid,os
nodes=json.loads(pathlib.Path('/inputs/nodes.json').read_text())
credential=json.loads(pathlib.Path('/secrets/bmc/bmc').read_text())
context=ssl.create_default_context(cafile='/secrets/bmc-ca/ca.crt')
header='Basic '+base64.b64encode((credential['username']+':'+credential['password']).encode()).decode()
def get(url):
    req=urllib.request.Request(url,headers={'Authorization':header,'Accept':'application/json'})
    with urllib.request.urlopen(req,context=context,timeout=15) as response:
        if response.status!=200:raise RuntimeError('unexpected HTTP status')
        return json.loads(response.read())
def verify(node):
    result={'name':node['name'],'url':node['url'],'passed':False,'gpu_readings':0}
    try:
        root=get(node['url']+'/redfish/v1')
        if not root.get('RedfishVersion'):raise RuntimeError('missing RedfishVersion')
        readings=[]
        for gpu in range(4):
            metrics=get(node['url']+'/redfish/v1/Systems/HGX_Baseboard_0/Processors/GPU_'+str(gpu)+'/EnvironmentMetrics')
            power=metrics.get('PowerWatts',{}).get('Reading')
            if not isinstance(power,(int,float)) or power<0:raise RuntimeError('missing GPU power reading')
            readings.append(power)
        result.update(passed=True,gpu_readings=len(readings),gpu_power_watts=readings,redfish_version=root['RedfishVersion'])
    except Exception as error:result['error_type']=type(error).__name__
    return result
try:
    addresses=sorted({result[4][0] for result in socket.getaddrinfo('kubernetes.default.svc',443)})
    storage=pathlib.Path('/data/prerequisite-probe.txt');probe=uuid.uuid4().hex
    with storage.open('w') as f:f.write(probe);f.flush();os.fsync(f.fileno())
    persistence_ok=storage.read_text()==probe
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(verify,nodes))
    passed=sum(x['passed'] for x in results)
    answer={'passed':passed==72 and persistence_ok and bool(addresses),'bmc_nodes':len(results),'bmc_passed':passed,'gpu_readings':sum(x['gpu_readings'] for x in results),'tls_certificate_verification':True,'BMC_methods_used':['GET'],'kubernetes_dns_addresses':addresses,'PVC_write_read_passed':persistence_ok,'nodes':results}
    print(json.dumps(answer));raise SystemExit(0 if answer['passed'] else 1)
except SystemExit:raise
except Exception as error:
    print(json.dumps({'passed':False,'error_type':type(error).__name__}));raise SystemExit(1)
"""
PG_PROBE_TABLE='__dps_prereq_'+uuid.uuid4().hex
PG_SQL=f"""SELECT json_build_object('server_version',current_setting('server_version'),'server_version_num',current_setting('server_version_num')::int,'database',current_database(),'role',current_user,'ssl',(SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()),'ssl_version',(SELECT version FROM pg_stat_ssl WHERE pid=pg_backend_pid()),'database_owner',pg_get_userbyid((SELECT datdba FROM pg_database WHERE datname=current_database()))); BEGIN; CREATE TABLE public.{PG_PROBE_TABLE}(id integer PRIMARY KEY); INSERT INTO public.{PG_PROBE_TABLE} VALUES (1); ALTER TABLE public.{PG_PROBE_TABLE} ADD COLUMN note text; ROLLBACK; SELECT json_build_object('migration_create_alter_insert_rollback',true);"""
try:
    version=kubejson('version')['serverVersion']['gitVersion'];match=re.match(r'v(\d+)\.(\d+)',version)
    condition(match and tuple(map(int,match.groups()))>=(1,31),'kubernetes_version',{'version':version,'minimum':'1.31'})
    nodes=kubejson('get','nodes')['items'];ready={node['metadata']['name']:any(c['type']=='Ready' and c['status']=='True' for c in node['status']['conditions']) for node in nodes}
    condition(bool(ready) and all(ready.values()),'nodes_ready',ready)
    condition(len(nodes)==1 and nodes[0]['metadata']['name']==TARGET_NODE,
              'single_physical_node',{'expected_node':TARGET_NODE,'observed_nodes':sorted(ready)})
    nodeinfo=nodes[0]['status']['nodeInfo']
    machine_id=pathlib.Path('/etc/machine-id').read_text().strip()
    boot_id=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    system_uuid_path=pathlib.Path('/sys/class/dmi/id/product_uuid')
    system_uuid=system_uuid_path.read_text().strip() if system_uuid_path.exists() else None
    host_matches={'machine_id_matches_host':nodeinfo.get('machineID','').lower()==machine_id.lower(),
                  'boot_id_matches_host':nodeinfo.get('bootID','').lower()==boot_id.lower(),
                  'system_uuid_matches_host':system_uuid is not None and nodeinfo.get('systemUUID','').lower()==system_uuid.lower()}
    condition(all(host_matches.values()),'physical_host_identity',
              dict(host_matches,host_hostname=command(['hostname']).stdout.strip(),
                   kubernetes_node=TARGET_NODE,identifier_values_printed=False))
    service_active=command(['systemctl','is-active','k3s'],check=False).stdout.strip()
    service_show=command(['systemctl','show','k3s','--property=MainPID','--property=FragmentPath']).stdout
    service_properties=dict(line.split('=',1) for line in service_show.splitlines() if '=' in line)
    service_pid=int(service_properties.get('MainPID','0'))
    process_path=pathlib.Path('/proc')/str(service_pid)
    executable=str((process_path/'exe').resolve()) if service_pid>0 else ''
    process_cgroup=(process_path/'cgroup').read_text() if service_pid>0 else ''
    process_args=(process_path/'cmdline').read_bytes().split(b'\0') if service_pid>0 else []
    native_service=service_active=='active' and service_pid>0 and pathlib.Path(executable).name=='k3s' and any(b'server' in arg.split() for arg in process_args) and 'k3s.service' in process_cgroup and not any(marker in process_cgroup for marker in ['docker','kubepods'])
    condition(native_service,'native_k3s_systemd_service',
              {'service_state':service_active,'service_pid':service_pid,'service_unit':service_properties.get('FragmentPath'),
               'service_executable':executable,'systemd_service_cgroup':('k3s.service' in process_cgroup),'server_process_role':any(b'server' in arg.split() for arg in process_args),
               'container_cgroup':any(marker in process_cgroup for marker in ['docker','kubepods'])})
    runtime=nodeinfo.get('containerRuntimeVersion','')
    condition(runtime.startswith('containerd://'),'native_node_containerd',
              {'container_runtime':runtime,'kubelet_version':nodeinfo.get('kubeletVersion'),
               'kubernetes_node':TARGET_NODE,'managed_by_native_k3s_service':native_service})
    deadline=time.monotonic()+180
    while True:
        components={}
        for name in ['traefik','coredns','local-path-provisioner']:
            deployment=kubejson('-n','kube-system','get','deployment',name)
            components[name]=deployment.get('status',{}).get('availableReplicas',0)>=deployment['spec'].get('replicas',1)
        if all(components.values()) or time.monotonic()>deadline:break
        time.sleep(5)
    condition(all(components.values()),'platform_components_ready',components)
    crd=kubejson('get','crd','ingressroutetcps.traefik.io');condition(any(c['type']=='Established' and c['status']=='True' for c in crd.get('status',{}).get('conditions',[])),'traefik_tcp_crd',crd['metadata']['name'])
    sc=kubejson('get','storageclass','local-path');annotations=sc['metadata'].get('annotations',{})
    condition(annotations.get('storageclass.kubernetes.io/is-default-class')=='true','default_storageclass',{'name':'local-path','provisioner':sc['provisioner'],'binding':sc.get('volumeBindingMode')})
    secrets={s['metadata']['name']:s for s in kubejson('-n',NAMESPACE,'get','secrets')['items']}
    expected={'bmc-shared-secret':{'bmc'},'dps-postgresql':{'password'},'dps-postgresql-ca':{'ca.crt'},'dps-bmc-ca':{'ca.crt'},'dps-jwt-keys':{'private-key.pem'},'dps-server-tls':{'ca.crt','tls.crt','tls.key'},'dps-agent-tls':{'ca.crt','tls.crt','tls.key'},'dps-ingress-tls':{'tls.crt','tls.key'}}
    secretcheck={name:{'present':name in secrets,'required_keys':sorted(keys),'keys_valid':name in secrets and keys.issubset(secrets[name].get('data',{}))} for name,keys in expected.items()}
    condition(all(s['keys_valid'] for s in secretcheck.values()),'required_secret_keys',secretcheck)
    label=secrets['bmc-shared-secret']['metadata'].get('labels',{}).get('app.kubernetes.io/component')
    bmc=json.loads(decode(secrets['bmc-shared-secret'],'bmc'))
    condition(label=='bmc-credentials' and {'username','password'}.issubset(bmc),'bmc_credential_store',{'secret':'bmc-shared-secret','label_valid':label=='bmc-credentials','credential_field_names_valid':{'username','password'}.issubset(bmc)})
    certcheck={}
    for name in ['dps-server-tls','dps-agent-tls','dps-ingress-tls']:
        cert=decode(secrets[name],'tls.crt')
        result=subprocess.run(['openssl','x509','-noout','-subject','-ext','subjectAltName','-enddate'],input=cert,capture_output=True)
        output=result.stdout.decode();valid=result.returncode==0
        if name=='dps-server-tls':valid=valid and 'DNS:api.dps.lab' in output and 'DNS:dps-server-grpc.dps.svc.cluster.local' in output
        if name=='dps-agent-tls':valid=valid and bool(re.search(r'CN\s*=\s*gb300-lab-agent',output))
        if name=='dps-ingress-tls':valid=valid and 'DNS:ui.dps.lab' in output
        certcheck[name]={'passed':valid,'public_certificate_identity':output.strip()}
    condition(all(x['passed'] for x in certcheck.values()),'tls_certificate_names',certcheck)
    jwt=subprocess.run(['openssl','pkey','-check','-noout'],input=decode(secrets['dps-jwt-keys'],'private-key.pem'),capture_output=True)
    condition(jwt.returncode==0,'jwt_private_key_valid',{'secret':'dps-jwt-keys','private_material_printed':False})
    release=json.loads(command(['helm','list','--all','--namespace',NAMESPACE,'--kube-context',CONTEXT,'--filter','^dps$','--output','json']).stdout)
    condition(not release,'dps_release_absent',{'matching_release_count':len(release)})
    render=command(['helm','template','dps',str(BASE/'dps-install/packages/dps-0.9.0.tgz'),'--namespace',NAMESPACE,'--kube-version',version,'--values',str(BASE/'dps-install/config/values.yaml')])
    rendered=BASE/'verification/reports/dps-prereq-rendered.yaml';rendered.write_text(render.stdout);rendered.chmod(0o600)
    resources=[x for x in yaml.safe_load_all(render.stdout) if isinstance(x,dict)];workloads=[x['metadata']['name'] for x in resources if x['kind'] in ['Deployment','StatefulSet']]
    condition(set(workloads)=={'dps-server','dps-server-agent','dps-ui'} and not any(x['kind']=='Secret' for x in resources),'helm_render',{'workloads':workloads,'secret_objects':sum(x['kind']=='Secret' for x in resources),'rendered_file':str(rendered)})
    runid=uuid.uuid4().hex[:8];prefix='dps-prereq-'+runid;podname=prefix+'-check';pvcname=prefix+'-storage';configname=prefix+'-inputs';labels={'app.kubernetes.io/component':'prerequisite-verification','dps-prereq-run':runid}
    report['temporary_resources']={'Pod':podname,'PVC':pvcname,'ConfigMap':configname};save()
    topology=json.loads((BASE/'dps-install/config/topology-4rack-dps09.json').read_text());targets=[{'name':e['Name'],'url':e['Redfish']['URL']} for e in topology['Entities'] if e['Type']=='ComputerSystem'];assert len(targets)==72
    items=[{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':configname,'namespace':NAMESPACE,'labels':labels},'data':{'nodes.json':json.dumps(targets)}},
    {'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':pvcname,'namespace':NAMESPACE,'labels':labels},'spec':{'storageClassName':'local-path','accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':'1Gi'}}}},
    {'apiVersion':'v1','kind':'Pod','metadata':{'name':podname,'namespace':NAMESPACE,'labels':labels},'spec':{'nodeSelector':{'kubernetes.io/hostname':TARGET_NODE},'restartPolicy':'Never','automountServiceAccountToken':False,'containers':[
        {'name':'postgres-check','image':'postgres:17','imagePullPolicy':'IfNotPresent','command':['psql','--set','ON_ERROR_STOP=1','--tuples-only','--no-align','--command',PG_SQL],
         'env':[{'name':k,'value':v} for k,v in {'PGHOST':'10.6.131.43','PGPORT':'15432','PGDATABASE':'dps','PGUSER':'dps','PGSSLMODE':'verify-full','PGSSLROOTCERT':'/secrets/postgresql/ca.crt'}.items()]+[{'name':'PGPASSWORD','valueFrom':{'secretKeyRef':{'name':'dps-postgresql','key':'password'}}}],
         'volumeMounts':[{'name':'postgres-ca','mountPath':'/secrets/postgresql','readOnly':True}],'resources':{'requests':{'cpu':'10m','memory':'32Mi'},'limits':{'cpu':'250m','memory':'128Mi'}}},
        {'name':'bmc-storage-dns-check','image':'python:3.13-slim','imagePullPolicy':'IfNotPresent','command':['python3','-c',PYTHON_CODE],
         'volumeMounts':[{'name':'inputs','mountPath':'/inputs','readOnly':True},{'name':'bmc','mountPath':'/secrets/bmc','readOnly':True},{'name':'bmc-ca','mountPath':'/secrets/bmc-ca','readOnly':True},{'name':'storage','mountPath':'/data'}],
         'resources':{'requests':{'cpu':'100m','memory':'64Mi'},'limits':{'cpu':'1','memory':'256Mi'}}}],
        'volumes':[{'name':'inputs','configMap':{'name':configname}},{'name':'postgres-ca','secret':{'secretName':'dps-postgresql-ca'}},{'name':'bmc','secret':{'secretName':'bmc-shared-secret'}},{'name':'bmc-ca','secret':{'secretName':'dps-bmc-ca'}},{'name':'storage','persistentVolumeClaim':{'claimName':pvcname}}]}}]
    manifest=MANIFESTDIR/(prefix+'.yaml');manifest.write_text(yaml.safe_dump_all(items,sort_keys=False));manifest.chmod(0o600);kubectl('apply','-f',str(manifest));print('Temporary prerequisite Pod/PVC created',podname,flush=True)
    deadline=time.monotonic()+900;last=-1
    while True:
        pod=kubejson('-n',NAMESPACE,'get','pod',podname);phase=pod['status'].get('phase','Pending');elapsed=900-(deadline-time.monotonic())
        if int(elapsed//20)!=last:print('Prerequisite Pod phase',phase,'elapsed',int(elapsed),'seconds',flush=True);last=int(elapsed//20)
        if phase in ['Succeeded','Failed'] or time.monotonic()>deadline:break
        time.sleep(5)
    pvc=kubejson('-n',NAMESPACE,'get','pvc',pvcname);report['storage_claim']={'phase':pvc['status'].get('phase'),'volumeName':pvc['spec'].get('volumeName'),'storageClass':'local-path'}
    logs={}
    for container in ['postgres-check','bmc-storage-dns-check']:
        result=kubectl('-n',NAMESPACE,'logs',podname,'-c',container,check=False);logs[container]=result.stdout
        (LOGDIR/(prefix+'-'+container+'.log')).write_text(result.stdout+result.stderr)
    pgresults=[json.loads(line) for line in logs['postgres-check'].splitlines() if line.strip().startswith('{')]
    pythonresults=[json.loads(line) for line in logs['bmc-storage-dns-check'].splitlines() if line.strip().startswith('{')]
    report['pod_phase']=phase;report['postgresql_results']=pgresults;report['bmc_storage_dns_results']=pythonresults[-1] if pythonresults else None;save()
    statuses=pod['status'].get('containerStatuses',[]);exit_codes={s['name']:s.get('state',{}).get('terminated',{}).get('exitCode') for s in statuses}
    condition(phase=='Succeeded' and len(exit_codes)==2 and all(code==0 for code in exit_codes.values()),'temporary_probe_pod',{'phase':phase,'container_exit_codes':exit_codes})
    condition(pvc['status'].get('phase')=='Bound','PVC_bound',report['storage_claim'])
    condition(len(pgresults)==2 and pgresults[0]['ssl'] and pgresults[0]['role']=='dps' and pgresults[0]['database']=='dps' and pgresults[0]['server_version_num']>=170000 and pgresults[1]['migration_create_alter_insert_rollback'],'postgresql_from_pod',pgresults)
    condition(bool(pythonresults) and pythonresults[-1]['passed'] and pythonresults[-1]['gpu_readings']==288,'BMC_DNS_storage_from_pod',{'nodes_passed':pythonresults[-1]['bmc_passed'],'gpu_readings':pythonresults[-1]['gpu_readings'],'DNS':pythonresults[-1]['kubernetes_dns_addresses'],'PVC_write_read_passed':pythonresults[-1]['PVC_write_read_passed'],'BMC_methods_used':pythonresults[-1]['BMC_methods_used']})
    kubectl('-n',NAMESPACE,'delete','pod/'+podname,'pvc/'+pvcname,'configmap/'+configname,'--ignore-not-found=true','--wait=true','--timeout=60s')
    report['temporary_resources_cleaned']=True;report['status']='passed';save();print(json.dumps({'status':'passed','report':str(REPORT),'checks':len(report['checks']),'BMC_nodes':72,'GPU_readings':288,'temporary_resources_cleaned':True}),flush=True)
except Exception as error:
    report['status']='failed';report['error']=str(error);save()
    if report.get('temporary_resources',{}).get('Pod'):
        events=kubectl('-n',NAMESPACE,'get','events','--field-selector','involvedObject.name='+report['temporary_resources']['Pod'],check=False)
        (LOGDIR/(report['temporary_resources']['Pod']+'-events.log')).write_text(events.stdout+events.stderr)
    print(json.dumps({'status':'failed','error':str(error),'report':str(REPORT)}),flush=True);sys.exit(1)
