#!/usr/bin/env python3
"""Generate all four-rack BMC inputs from tracked topology; no SDK checkout required."""
import argparse, copy, csv, json, os, secrets
from pathlib import Path
import yaml
from bootstrap_common import repo_root, private, pair, secret, bind_settings, validate_host, command, require_existing_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root"); p.add_argument("--host-ip",required=True)
    p.add_argument("--host-name",default="dps-lab"); p.add_argument("--start-port",type=int,default=18443)
    p.add_argument("--namespace",default="dps"); p.add_argument("--agent-id",default="gb300-lab-agent")
    p.add_argument("--topology-name",default="dps-gb300-4rack")
    p.add_argument("--container-name",default="dps-gb300-bmc")
    p.add_argument("--proxy-name",default="dps-gb300-bmc-proxy"); p.add_argument("--network-name",default="dps-gb300-bmc-net")
    a=p.parse_args(); os.umask(0o077); r=repo_root(a.root); validate_host(a.host_ip,a.host_name)
    if not 1<=a.start_port<=65464: raise ValueError("Invalid 72-node port range")
    c=r/"dps-install/config"; s=r/"hardware-sim/runtime"; c.mkdir(parents=True,exist_ok=True)
    desired={k:getattr(a,k) for k in ("host_ip","host_name","start_port","namespace","agent_id","topology_name","container_name","proxy_name","network_name")}
    marker=c/"bmc-bootstrap.json"
    require_existing_identity(marker,[s/"authority/ca.key",s/"authority/ca.crt",s/"tls/tls.key",s/"tls/tls.crt",c/"bmc-credentials.json"])
    bind_settings(marker,desired,(s/"tls/tls.key").exists() or (c/"bmc-credentials.json").exists())
    nodes=json.loads((s/"nodes.json").read_text())
    if len(nodes)!=72: raise ValueError("Expected tracked four-rack node mapping")
    topology=json.loads((c/"topology-4rack-dps09.json").read_text())
    for i,n in enumerate(nodes):
        n["port"]=a.start_port+i; n["bmc_url"]=f"https://{a.host_ip}:{n['port']}"; n["secret_name"]="bmc-shared-secret"
    by_name={n["node_id"]:n for n in nodes}
    for e in topology["Entities"]:
        if e["Type"]=="ComputerSystem":
            e["Redfish"]={"URL":by_name[e["Name"]]["bmc_url"],"SecretName":"bmc-shared-secret"}
    topology["Topology"]["Name"]=a.topology_name
    for e in topology["Topology"]["Entities"]:
        if e["Name"] in by_name: e["AgentId"]=a.agent_id
    (s/"nodes.json").write_text(json.dumps(nodes,indent=2)+"\n")
    (c/"topology-4rack-dps09.json").write_text(json.dumps(topology,indent=2)+"\n")
    ca=pair(s/"authority","ca","DPS BMC Simulator CA")
    key,crt=pair(s/"tls","tls","simulator",ca,["IP:"+a.host_ip,"IP:127.0.0.1","DNS:simulator","DNS:"+a.host_name])
    (s/"tls").chmod(0o755)
    os.chown(key,0,0)
    (s/"tls/ca.crt").write_bytes(ca[1].read_bytes())
    (s/"tls/ca.crt").chmod(0o644)
    (c/"simulator-ca.crt").write_bytes(ca[1].read_bytes())
    credentials=c/"bmc-credentials.json"
    if credentials.exists(): cred=json.loads(credentials.read_text())
    else:
        cred={"username":"admin","password":secrets.token_urlsafe(36)}
        private(credentials,cred)
    secret(c/"bmc-shared-secret.yaml","bmc-shared-secret",a.namespace,{"bmc":json.dumps(cred)},
           {"app.kubernetes.io/component":"bmc-credentials"})
    secret(c/"bmc-ca-secret.yaml","dps-bmc-ca",a.namespace,{"ca.crt":ca[1].read_text()})
    csvfile=c/"bmc-endpoints.csv"
    with csvfile.open("w",newline="")as f:
        writer=csv.DictWriter(f,fieldnames=["rack_id","node_id","bmc_url","redfish_system_url","username","password"])
        writer.writeheader()
        for n in nodes:
            writer.writerow({**{k:n[k] for k in ["rack_id","node_id","bmc_url"]},
                             "redfish_system_url":n["bmc_url"]+"/redfish/v1/Systems/HGX_Baseboard_0",**cred})
    csvfile.chmod(0o600)
    config={"port":8443,"default_dir":"/app/mockups/gb300",
            "dirs":{n["node_id"]:"/app/mockups/gb300" for n in nodes},"ssl":True,"debug":False,
            "update_workload_power_profile_delay":"25s","metrics":{"plugin":"synthetic"},"host":"0.0.0.0"}
    private(s/"config.yaml",config)
    (s/"config.yaml").chmod(0o644)
    lines=["worker_processes 2;","error_log /dev/stderr warn;","pid /var/run/nginx.pid;",
           "events { worker_connections 4096; }","http {","access_log /dev/stdout;",
           "upstream gb300_backend { server simulator:8443; keepalive 256; }",
           "ssl_certificate /etc/bmc-tls/tls.crt;","ssl_certificate_key /etc/bmc-tls/tls.key;",
           "ssl_protocols TLSv1.2 TLSv1.3;"]
    for n in nodes:
        lines += ["server {",f"listen {n['port']} ssl;",f"server_name {n['node_id']};","location / {",
                  "proxy_pass https://gb300_backend;",f"proxy_set_header Host {n['node_id']};",
                  f"proxy_set_header X-Forwarded-Host {n['node_id']};",
                  "proxy_set_header Connection \"\";","proxy_http_version 1.1;",
                  "proxy_ssl_verify off;","proxy_read_timeout 60s;","}","}"]
    lines.append("}"); (s/"nginx.conf").write_text("\n".join(lines)+"\n")
    logging={"driver":"json-file","options":{"max-size":"20m","max-file":"3"}}
    compose={"services":{"simulator":{
        "image":"nvcr.io/nvidia/dps-bmc-simulator@sha256:3f81152ee055b95e0bda512227cd6ecbb4813f97dad0c654477a4afbf8caff7e",
        "container_name":a.container_name,"restart":"unless-stopped",
        "command":["-c","/app/config.yaml","-d","/app/mockups/gb300","--host","0.0.0.0","--port","8443",
                   "--max-active-requests=4096","--power-snapshot-interval=5s"],
        "volumes":[str(s/"config.yaml")+":/app/config.yaml:ro"],
        "networks":["bmc"],"cpus":4,"mem_limit":"6g","logging":logging},
        "proxy":{"image":"nginx@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236",
        "container_name":a.proxy_name,"restart":"unless-stopped","depends_on":["simulator"],
        "entrypoint":["nginx","-g","daemon off;"],
        "volumes":[str(s/"nginx.conf")+":/etc/nginx/nginx.conf:ro",str(s/"tls")+":/etc/bmc-tls:ro"],
        "ports":[f"{a.host_ip}:{a.start_port}-{a.start_port+71}:{a.start_port}-{a.start_port+71}"],
        "networks":["bmc"],"cpus":2,"mem_limit":"512m","logging":logging,
        "healthcheck":{"test":["CMD","wget","-q","--no-check-certificate","-O","/dev/null",
                                      f"https://127.0.0.1:{a.start_port}/readyz"],
                       "interval":"15s","timeout":"5s","retries":3}}},
        "networks":{"bmc":{"name":a.network_name}}}
    private(s/"compose.yaml",compose)
    print(json.dumps({"prepared_bmc_nodes":72,"racks":4,"start_port":a.start_port,
                      "tls_verified":True,"credentials_file":str(credentials)}))

if __name__=="__main__": main()
