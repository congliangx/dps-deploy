#!/usr/bin/env python3
"""Install BMC, PostgreSQL, LDAP, native K3s and DPS 0.9 from a clean checkout."""
import argparse, fnmatch, hashlib, ipaddress, json, os, re, shutil, socket, subprocess, sys, time
from pathlib import Path
import yaml
from bootstrap_common import repo_root, private, validate_host

def execute(args, env=None, stdin=None):
    r=subprocess.run([str(x)for x in args],input=stdin,text=True,env=env,capture_output=True)
    if r.returncode:raise RuntimeError("Command failed: "+" ".join(str(x)for x in args[:3]))
    return r.stdout

def ensure_native_ingress(env):
    # Node Ready can precede installation of the bundled Traefik chart and CRDs.
    crds = ["crd/ingressroutes.traefik.io", "crd/ingressroutetcps.traefik.io"]
    for attempt in range(90):
        result = subprocess.run(["kubectl", "get", *crds, "-o", "name"], env=env, text=True, capture_output=True)
        if result.returncode == 0:
            break
        time.sleep(2)
    else:
        raise RuntimeError("Native Traefik ingress CRDs did not become available")
    execute(["kubectl", "wait", "--for=condition=Established", *crds, "--timeout=180s"], env)
    execute(["kubectl", "-n", "kube-system", "rollout", "status", "deployment/traefik", "--timeout=180s"], env)

def ensure_unused_hosts(settings, env):
    """Reject API/UI routes owned by another instance before installing services."""
    resources = ["ingresses.networking.k8s.io"]
    available = set(execute(["kubectl", "api-resources", "--api-group=traefik.io", "-o", "name"], env).split())
    resources.extend(sorted(available & {"ingressroutes.traefik.io", "ingressroutetcps.traefik.io"}))
    desired = {settings["api_name"].lower(), settings["ui_name"].lower()}
    for resource in resources:
        objects = json.loads(execute(["kubectl", "get", resource, "--all-namespaces", "-o", "json"], env))
        for obj in objects.get("items", []):
            meta = obj["metadata"]
            release = meta.get("labels", {}).get("app.kubernetes.io/instance") or meta.get("annotations", {}).get("meta.helm.sh/release-name")
            if meta.get("namespace") == settings["namespace"] and release == settings["release"]:
                continue
            spec = obj.get("spec", {})
            hosts = {x["host"].lower() for x in spec.get("rules", []) if x.get("host")}
            for entry in spec.get("tls", []) if isinstance(spec.get("tls"), list) else []:
                hosts.update(str(h).lower() for h in entry.get("hosts", []))
            for route in spec.get("routes", []):
                match = route.get("match", "")
                for expression in re.findall(r"\bHost(?:SNI)?\(([^)]*)\)", match):
                    hosts.update(h.lower() for h in re.findall(r"[\x60\x27\x22]([^\x60\x27\x22]+)[\x60\x27\x22]", expression))
            if any(fnmatch.fnmatchcase(host, pattern) for host in desired for pattern in hosts):
                owner = meta.get("namespace", "") + "/" + meta.get("name", "")
                raise RuntimeError("API/UI hostname already routed by another instance: " + owner)

def recipe(root,name,s,env=None,args=None):
    src=(root/"dps-install/scripts"/name).read_text()
    for old,new in [("/raid/vince/deploy",str(root)),("10.6.131.43",s["host_ip"]),
                    ("L20-12",s["host_name"]),("l20-12",s["host_name"].lower()),("bond0",s["interface"]),
                    ("/run/systemd/resolve/resolv.conf",s["resolv_conf"]),
                    ("gb300-lab-agent",s["agent_id"])]:
        src=src.replace(old,new)
    target=root/"dps-install/config/bootstrap-recipes"/name
    target.parent.mkdir(parents=True,exist_ok=True)
    if name=="install-kubernetes.sh":
        child=(root/"dps-install/scripts/refresh-kubeconfig.py").read_text()
        for old,new in [("/raid/vince/deploy",str(root)),("10.6.131.43",s["host_ip"]),
                        ("L20-12",s["host_name"]),("l20-12",s["host_name"].lower())]:
            child=child.replace(old,new)
        childpath=target.parent/"refresh-kubeconfig.py";childpath.write_text(child);childpath.chmod(0o700)
        src=src.replace("$BASE/dps-install/scripts/refresh-kubeconfig.py",str(childpath)).replace(str(root)+"/dps-install/scripts/refresh-kubeconfig.py",str(childpath))
    if name=="update-topology.sh":
        child=(root/"dps-install/scripts/register-devices.sh").read_text().replace("/raid/vince/deploy",str(root))
        childpath=target.parent/"register-devices.sh";childpath.write_text(child);childpath.chmod(0o700)
        src=src.replace("$base/dps-install/scripts/register-devices.sh",str(childpath)).replace(str(root)+"/dps-install/scripts/register-devices.sh",str(childpath))
        full=s["release"]if "dps"in s["release"]else s["release"]+"-dps"
        src=src.replace("'-n','dps','get','service','dps-server-http'",
                        "'-n',"+repr(s["namespace"])+",'get','service',"+repr(full+"-server-http"))
    target.write_text(src);target.chmod(0o700)
    return execute(["bash"if name.endswith(".sh")else sys.executable,target,*(args or [])],env=env)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root");p.add_argument("--config")
    for key in ["host-ip","host-name","interface","namespace","release","agent-id","api-name","ui-name","instance-prefix","pg-subnet"]:
        p.add_argument("--"+key)
    for key in ["pg-port","ldap-port","bmc-start-port"]:p.add_argument("--"+key,type=int)
    p.add_argument("--kubeconfig",help="Explicit reuse of an existing native Kubernetes cluster")
    p.add_argument("--download-only",action="store_true");p.add_argument("--prepare-only",action="store_true")
    a=p.parse_args();os.umask(0o077);root=repo_root(a.root)
    if os.geteuid()!=0:raise ValueError("Run as root")
    if not (root/"dps-install/config/values.example.yaml").exists():raise ValueError("Use a repository checkout")
    cfg=yaml.safe_load(Path(a.config).read_text())if a.config else {}
    defaults={"host_name":socket.gethostname(),"interface":"bond0","namespace":"dps","release":"dps",
        "agent_id":"gb300-lab-agent","api_name":"api.dps.lab","ui_name":"ui.dps.lab","instance_prefix":"dps",
        "pg_port":15432,"ldap_port":1636,"bmc_start_port":18443,"pg_subnet":"172.30.90.0/24",
        "resolv_conf":"/run/systemd/resolve/resolv.conf"if Path("/run/systemd/resolve/resolv.conf").exists()else"/etc/resolv.conf"}
    s={**defaults,**(cfg or {})}
    for k in defaults.keys()|{"host_ip"}:
        if getattr(a,k,None)is not None:s[k]=getattr(a,k)
    if not s.get("host_ip"):raise ValueError("Specify --host-ip")
    validate_host(s["host_ip"],s["host_name"])
    for key in ["namespace","release","agent_id","instance_prefix"]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,45}",s[key]):raise ValueError("Invalid "+key)
    for key in ["api_name","ui_name"]:validate_host(s["host_ip"],s[key])
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}",s["interface"]):raise ValueError("Invalid interface")
    if ipaddress.ip_network(s["pg_subnet"]).version!=4:raise ValueError("IPv4 Docker subnet required")
    s.update({"root":str(root),"pg_container":s["instance_prefix"]+"-postgresql",
        "ldap_container":s["instance_prefix"]+"-openldap","bmc_container":s["instance_prefix"]+"-gb300-bmc",
        "proxy_container":s["instance_prefix"]+"-gb300-bmc-proxy","pg_network":s["instance_prefix"]+"-postgresql-net",
        "kubeconfig":str(root/"dps-install/config/kubernetes/kubeconfig.yaml")})
    c=root/"dps-install/config";state=c/"bootstrap-settings.json"
    if state.exists():
        old=json.loads(state.read_text())
        for k,v in s.items():
            if old.get(k)!=v and not (k=="resolv_conf" and k not in old):raise RuntimeError("Bootstrap parameters changed: "+k)
    elif (c/"tls/jwt-private-key.pem").exists()or any((root/"dps-install/data"/d).exists()and any((root/"dps-install/data"/d).iterdir())for d in ["postgresql","ldap"]):
        raise RuntimeError("Existing non-bootstrap installation; use a clean checkout")
    for path in [root/"verification/reports",root/"verification/logs",root/"verification/archive/prerequisites",
                 c/"kubernetes",c/"dpsctl",c/"helm",root/"dps-install/packages"]:
        path.mkdir(parents=True,exist_ok=True)
    private(state,s)
    execute([sys.executable,root/"dps-install/scripts/download-artifacts.py","--root",root,"--component","all"])
    if a.download_only:print("Artifacts checked; no services installed.");return
    image=json.loads((c/"ldap/runtime-build.json").read_text())["image_id"]
    scripts=root/"dps-install/scripts";ip=s["host_ip"];host=s["host_name"];ns=s["namespace"]
    def generate(name,extra):
        execute([sys.executable,scripts/name,"--root",root,"--host-ip",ip,"--host-name",host,"--namespace",ns,*extra])
        print("Prepared "+name,flush=True)
    generate("prepare-bmc-fresh.py",["--start-port",s["bmc_start_port"],"--agent-id",s["agent_id"],
        "--container-name",s["bmc_container"],"--proxy-name",s["proxy_container"],"--network-name",s["instance_prefix"]+"-bmc-net"])
    generate("prepare-postgresql.py",["--port",s["pg_port"],"--container-name",s["pg_container"],
        "--network-name",s["pg_network"],"--subnet",s["pg_subnet"]])
    generate("prepare-ldap-fresh.py",["--port",s["ldap_port"],"--container-name",s["ldap_container"],"--image",image])
    generate("prepare-dps-fresh.py",["--release",s["release"],"--agent-id",s["agent_id"],
        "--api-name",s["api_name"],"--ui-name",s["ui_name"],"--pg-port",s["pg_port"],
        "--ldap-port",s["ldap_port"],"--pg-subnet",s["pg_subnet"]])
    if a.prepare_only:print("Passwords, certificates and 13 Secrets prepared; no services started.");return
    for name in [s[k]for k in ["pg_container","ldap_container","bmc_container","proxy_container"]]:
        inspect=subprocess.run(["docker","inspect",name],capture_output=True,text=True)
        if inspect.returncode==0 and not any(m.get("Source","").startswith(str(root)+"/")for m in json.loads(inspect.stdout)[0].get("Mounts",[])):
            raise RuntimeError("Unrelated Docker container: "+name)
    for binary,version,installer in [("helm","v3.22.0","install-tools.py"),("kubectl","v1.34.12","install-tools.py"),("dpsctl","0.9.0","install-dpsctl.sh")]:
        if not shutil.which(binary):recipe(root,installer,s,args=["--only",binary] if installer=="install-tools.py" else None)
        text=execute([binary,"version","--client=true","-o","json"]if binary=="kubectl"else
                     [binary,"version","--template","{{.Version}}"]if binary=="helm"else[binary,"--version"])
        if version not in text:raise RuntimeError("Existing "+binary+" version differs from pinned requirement")
    env=dict(os.environ,KUBECONFIG=s["kubeconfig"],HELM_CONFIG_HOME=str(c/"helm"),
             HELM_CACHE_HOME=str(root/"dps-install/data/helm-cache"),HELM_DATA_HOME=str(root/"dps-install/data/helm-data"),
             DPSCTL_HOST=s["api_name"],DPSCTL_PORT="443",DPSCTL_CA_CERT_PATH=str(c/"tls/ca.crt"),
             DPSCTL_CREDENTIALS_PATH=str(c/"dpsctl/credentials.yaml"),DPSCTL_LOG_FILE=str(root/"verification/logs/dpsctl.log"))
    if a.kubeconfig:
        source=Path(a.kubeconfig).resolve()
        if source==Path(s["kubeconfig"]).resolve():raise ValueError("Provide an external source kubeconfig")
        shutil.copy2(source,s["kubeconfig"]);Path(s["kubeconfig"]).chmod(0o600)
    else:
        text=(root/"dps-install/config/kubernetes/k3s.yaml").read_text()
        for old,new in [("/raid/vince/deploy",str(root)),("10.6.131.43",ip),("L20-12",host),("l20-12",host.lower()),("bond0",s["interface"]),("/run/systemd/resolve/resolv.conf",s["resolv_conf"]),
                    ("gb300-lab-agent",s["agent_id"])]:text=text.replace(old,new)
        private(c/"kubernetes/k3s.yaml",text)
        recipe(root,"install-kubernetes.sh",s,env)
    kube=yaml.safe_load(Path(s["kubeconfig"]).read_text());s["kube_context"]=kube["current-context"];private(state,s)
    ensure_native_ingress(env)
    ensure_unused_hosts(s, env)
    context=next(x for x in kube["contexts"]if x["name"]==kube["current-context"])
    cluster=next(x for x in kube["clusters"]if x["name"]==context["context"]["cluster"])
    from urllib.parse import urlparse
    endpoint=urlparse(cluster["cluster"]["server"])
    v=yaml.safe_load((c/"values.yaml").read_text())
    rule=v["power-steering"]["controller"]["extraEgressRules"][-1]
    rule["to"][0]["ipBlock"]["cidr"]=socket.gethostbyname(endpoint.hostname)+"/32";rule["ports"][0]["port"]=endpoint.port or 6443
    private(c/"values.yaml",v)
    keys=["KUBECONFIG","HELM_CONFIG_HOME","HELM_CACHE_HOME","HELM_DATA_HOME"]
    envfile="".join("export "+k+"="+json.dumps(value)+"\n"for k,value in env.items()if k in keys or k.startswith("DPSCTL_"))
    envfile+="export DPS_KUBE_CONTEXT="+json.dumps(s["kube_context"])+"\nexport DPS_NAMESPACE="+json.dumps(ns)+"\n"
    private(c/"dps-env.sh",envfile)
    kb=["kubectl","--namespace",ns];label=hashlib.sha256(str(root).encode()).hexdigest()[:16]
    result=subprocess.run(["kubectl","get","namespace",ns,"-o","json"],env=env,text=True,capture_output=True)
    if result.returncode:
        execute(["kubectl","create","namespace",ns],env);execute(["kubectl","label","namespace",ns,"dps-bootstrap-root="+label],env)
    elif json.loads(result.stdout)["metadata"].get("labels",{}).get("dps-bootstrap-root")!=label:
        raise RuntimeError("Unowned existing namespace: "+ns)
    for role,file in [("bmc",root/"hardware-sim/runtime/compose.yaml"),("postgresql",c/"postgresql/compose.yaml"),("ldap",c/"ldap/compose.yaml")]:
        execute(["docker","compose","-p",s["instance_prefix"]+"-"+role,"-f",file,"up","-d"])
        print("Started "+role+" services",flush=True)
    execute(["docker","exec",s["proxy_container"],"nginx","-t"])
    execute(["docker","exec",s["proxy_container"],"nginx","-s","reload"])
    for name in [s["pg_container"],s["ldap_container"],s["proxy_container"]]:
        for tick in range(90):
            info=json.loads(execute(["docker","inspect",name]))[0]["State"]
            if info.get("Health",{}).get("Status")=="healthy":break
            time.sleep(2)
        else:raise RuntimeError("Container did not become healthy: "+name)
    hosts=Path("/etc/hosts");text=hosts.read_text();missing=[]
    for domain in [s["api_name"],s["ui_name"]]:
        try:addresses={e[4][0]for e in socket.getaddrinfo(domain,None,socket.AF_INET)}
        except socket.gaierror:addresses=set()
        if addresses and addresses!={ip}:raise RuntimeError("Hostname points elsewhere: "+domain)
        if not addresses:missing.append(domain)
    if missing:
        backup=root/"verification/archive/prerequisites/hosts.before-bootstrap"
        if not backup.exists():backup.write_text(text)
        with hosts.open("a")as f:f.write("\n"+ip+" "+" ".join(missing)+" # DPS bootstrap "+ns+"\n")
    secretfiles=[c/"postgresql-secret.yaml",c/"postgresql-ca-secret.yaml",c/"bmc-shared-secret.yaml",c/"bmc-ca-secret.yaml",
        *sorted((c/"tls").glob("*-secret.yaml")),*sorted((c/"ldap").glob("*-secret.yaml")),*sorted((c/"prs").glob("*-secret.yaml"))]
    if len(secretfiles)!=13:raise RuntimeError("Expected exactly 13 external Secrets")
    for file in secretfiles:execute([*kb,"apply","--server-side","--field-manager=dps-bootstrap","-f",file],env)
    chart=root/"dps-install/packages/dps-0.9.0.tgz"
    rendered=execute(["helm","template",s["release"],chart,"-n",ns,"-f",c/"values.yaml"],env);images=set()
    def visit(x):
        if isinstance(x,dict):
            if isinstance(x.get("image"),str):images.add(x["image"])
            for val in x.values():visit(val)
        elif isinstance(x,list):
            for val in x:visit(val)
    for document in yaml.safe_load_all(rendered):visit(document)
    sources=json.loads((c/"artifact-sources.json").read_text())["images"];pinned={i["tag"]:i for i in sources if i.get("tag")}
    for name in sorted(images):
        if name not in pinned:raise RuntimeError("Unpinned chart image: "+name)
        reference=pinned[name]["image_digest"];target=json.loads(execute(["docker","image","inspect",reference]))[0]["Id"]
        if json.loads(execute(["docker","image","inspect",name]))[0]["Id"]!=target:raise RuntimeError("Chart image identity changed: "+name)
    archive=root/"dps-install/packages/bootstrap-kubernetes-images.tar"
    execute(["docker","save","-o",archive,*sorted(images)]);execute(["k3s","ctr","-n","k8s.io","images","import",archive])
    print("Pinned "+str(len(images))+" images imported into native containerd",flush=True)
    execute(["helm","upgrade","--install",s["release"],chart,"--namespace",ns,"--values",c/"values.yaml","--wait","--timeout","10m"],env)
    account=json.loads((c/"dps-access.json").read_text())
    out=execute(["dpsctl","--no-retry","login","--username",account["username"],"--password-stdin"],env,account["password"]+"\n")
    if not json.loads(out[out.find("{"):]).get("status",{}).get("ok"):raise RuntimeError("LDAP login failed")
    execute(["dpsctl","--no-retry","device","upsert",c/"gb300-power-shelf-devices.yaml"],env)
    text=execute(["dpsctl","--no-retry","topology","list"],env);topologies=json.loads(text[text.find("{"):])
    if not any(t["topology_name"]=="dps-gb300-4rack"for t in topologies.get("topologies",[])):
        result=execute(["dpsctl","--no-retry","topology","import",c/"topology-4rack-dps09.json"],env)
        if not json.loads(result[result.find("{"):]).get("status",{}).get("ok"):raise RuntimeError("Topology import failed")
    recipe(root,"update-topology.sh",s,env)
    execute(["dpsctl","--no-retry","settings","update","--set","prs_enabled=true","--set","prs_headroom_percent=-15","--set","prs_scheduler_interval_seconds=5"],env)
    s["installation_complete"]=True;private(state,s)
    print(json.dumps({"installed":True,"namespace":ns,"release":s["release"],"bmc_nodes":72,
        "ui":"https://"+s["ui_name"],"api":s["api_name"]+":443","credentials_file":str(c/"dps-access.json"),
        "topology_active":False,"bmc_power_writes":False}))

if __name__=="__main__":
    try:main()
    except Exception as e:print("Cold installation stopped: "+str(e),file=sys.stderr);sys.exit(1)
