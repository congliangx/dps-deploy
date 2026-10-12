#!/usr/bin/env python3
"""Prepare DPS directly with LDAP, stable fresh JWT/TLS and PRS/S3 inputs."""
import sys
sys.dont_write_bytecode = True
import argparse, copy, ipaddress, json, os, secrets
from pathlib import Path
from deployment_context import context_from_cli
ctx = context_from_cli()
import yaml
from bootstrap_common import repo_root, private, pair, secret, bind_settings, command, validate_host, require_existing_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root"); p.add_argument("--host-ip",default=ctx.settings["host_ip"])
    p.add_argument("--host-name",default=ctx.settings["host_name"]);p.add_argument("--namespace",default=ctx.settings["namespace"])
    p.add_argument("--release",default=ctx.settings["release"]);p.add_argument("--agent-id",default=ctx.settings["agent_id"])
    p.add_argument("--api-name",default=ctx.settings["api_name"]);p.add_argument("--ui-name",default=ctx.settings["ui_name"])
    p.add_argument("--pg-port",type=int,default=ctx.settings["pg_port"]);p.add_argument("--ldap-port",type=int,default=ctx.settings["ldap_port"])
    p.add_argument("--pg-subnet",default=ctx.settings["pg_subnet"])
    p.add_argument("--kube-api-ip");p.add_argument("--kube-api-port",type=int,default=ctx.settings["kube_api_port"])
    a=p.parse_args();os.umask(0o077);r=repo_root(a.root);validate_host(a.host_ip,a.host_name)
    c=r/"dps-install/config";t=c/"tls"
    desired={k:getattr(a,k)for k in ["host_ip","host_name","namespace","release","agent_id","api_name",
                                     "ui_name","pg_port","ldap_port","pg_subnet","kube_api_ip","kube_api_port"]}
    marker=c/"dps-bootstrap.json"
    require_existing_identity(marker, [t/(name+suffix) for name in ["ca","server","agent","ingress"] for suffix in [".key",".crt"]] +
                              [t/"jwt-private-key.pem",c/"prs/s3-credentials.json"])
    bind_settings(marker,desired,(t/"jwt-private-key.pem").exists() or (c/"prs/s3-credentials.json").exists())
    account=json.loads((c/"dps-access.json").read_text())
    if account.get("authentication")!="ldap":raise ValueError("Fresh LDAP account is required")
    full=a.release if "dps" in a.release else a.release+"-dps"
    ca=pair(t,"ca","DPS Bootstrap CA")
    identities=[("server",full+"-server-grpc","serverAuth",["DNS:"+a.api_name,
        "DNS:"+full+"-server-grpc","DNS:"+full+"-server-grpc."+a.namespace,
        "DNS:"+full+"-server-grpc."+a.namespace+".svc",
        "DNS:"+full+"-server-grpc."+a.namespace+".svc.cluster.local","IP:"+a.host_ip]),
        ("agent",a.agent_id,"clientAuth",["DNS:"+a.agent_id]),
        ("ingress",a.ui_name,"serverAuth",["DNS:"+a.ui_name,"DNS:"+a.api_name,"IP:"+a.host_ip])]
    for name,cn,purpose,sans in identities:
        key,crt=pair(t,name,cn,ca,sans,purpose)
        secret(t/("dps-"+("agent" if name=="agent" else name)+"-tls-secret.yaml"),
               "dps-"+("agent" if name=="agent" else name)+"-tls",a.namespace,
               {"ca.crt":ca[1].read_text(),"tls.crt":crt.read_text(),"tls.key":key.read_text()})
    jwt=t/"jwt-private-key.pem"
    if not jwt.exists():command(["openssl","genrsa","-out",jwt,"3072"]);jwt.chmod(0o600)
    command(["openssl","pkey","-in",jwt,"-check","-noout"])
    secret(t/"dps-jwt-keys-secret.yaml","dps-jwt-keys",a.namespace,{"private-key.pem":jwt.read_text()})
    prs=c/"prs";prs.mkdir(parents=True,exist_ok=True)
    s3file=prs/"s3-credentials.json"
    if s3file.exists():s3=json.loads(s3file.read_text())
    else:
        s3={"bucket":"dps-prs","secret_name":"dps-prs-s3",
            "admin_access_key_id":secrets.token_urlsafe(18),"admin_secret_access_key":secrets.token_urlsafe(40)}
        private(s3file,s3)
    identity={"identities":[{"name":"dps-prs","credentials":[{"accessKey":s3["admin_access_key_id"],
             "secretKey":s3["admin_secret_access_key"]}],"actions":["Admin","Read","Write"]}]}
    secret(prs/"s3-secret.yaml","dps-prs-s3",a.namespace,{"admin_access_key_id":s3["admin_access_key_id"],
        "admin_secret_access_key":s3["admin_secret_access_key"],"seaweedfs_s3_config":json.dumps(identity)})
    secret(prs/"dps-auth-secret.yaml","dps-prs-dps-auth",a.namespace,
           {"ldap-credentials":json.dumps({"username":account["username"],"password":account["password"]})})
    v=yaml.safe_load(ctx.source_path("dps-install/config/values.example.yaml").read_text())
    v["fullnameOverride"]=full
    v["global"]["postgresql"]["host"]=a.host_ip
    v["global"]["postgresql"]["service"]["ports"]["postgresql"]=str(a.pg_port)
    v["postgresql"]["image"]["tag"]="17"
    v["dps"]["ingress"]["hostname"]=a.api_name
    v["ui"]["ingress"]["hostname"]=a.ui_name
    v["ui"]["ingress"]["tls"][0]["hosts"]=[a.ui_name]
    v["ui"]["api"]["hostname"]=full+"-server-http."+a.namespace+".svc.cluster.local"
    v["dps"]["cors"]["allowedOrigins"]="https://"+a.ui_name
    v["dps"]["ldap"]["serverUrl"]=f"ldaps://{a.host_ip}:{a.ldap_port}"
    v["agent"]["agentID"]=a.agent_id
    v["dps"]["grpcServiceMTLSCN"]["nvidia.dcpower.v1.DPSAgentService"]=[a.agent_id]
    v["power-steering"]["controller"]["cluster"]["dps"]["host"]=full+"-server-grpc"
    power_full=a.release+"-power"
    v["power-steering"]["config"]["fullnameOverride"]=power_full+"-config"
    v["power-steering"]["controller"]["fullnameOverride"]=power_full+"-controller"
    v["dps"]["prs"]["hostPort"]=f"http://{power_full}-config.{a.namespace}.svc.cluster.local:8000"
    v["dps"]["prs"]["controllerHostPort"]=f"http://{power_full}-controller.{a.namespace}.svc.cluster.local:8001"
    bridge=str(ipaddress.ip_network(a.pg_subnet)[2])
    egress=[{"to":[{"ipBlock":{"cidr":a.host_ip+"/32"}}],"ports":[{"port":a.pg_port,"protocol":"TCP"}]},
            {"to":[{"ipBlock":{"cidr":bridge+"/32"}}],"ports":[{"port":5432,"protocol":"TCP"}]}]
    v["power-steering"]["config"]["extraEgressRules"]=copy.deepcopy(egress)
    v["power-steering"]["controller"]["extraEgressRules"]=copy.deepcopy(egress)+[
        {"to":[{"ipBlock":{"cidr":(a.kube_api_ip or a.host_ip)+"/32"}}],
         "ports":[{"port":a.kube_api_port,"protocol":"TCP"}]}]
    private(c/"values.yaml",v)
    print(json.dumps({"authenticator":"ldap","prs_enabled":True,"new_or_reused_local_identity":True,
                      "namespace":a.namespace,"release":a.release,"credentials_file":str(c/"dps-access.json")}))

if __name__=="__main__":main()
