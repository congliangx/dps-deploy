#!/usr/bin/env python3
"""Prepare LDAP Secrets while retaining recorded service/identity; fresh installs use the producer."""
import sys
sys.dont_write_bytecode = True
import json, os, subprocess
from pathlib import Path
import yaml
from deployment_context import context_from_cli
from bootstrap_common import secret
ctx = context_from_cli()
os.umask(0o077)
c = ctx.runtime_path("dps-install/config")
l = c/"ldap"
identity = l/"credentials.json"
if not identity.exists():
    # No historical image ID/archive or alwaysAllow account is required for a new instance.
    manifest = l/"runtime-build.json"
    if not manifest.is_file():
        raise SystemExit("Acquire the pinned LDAP build before fresh LDAP preparation")
    image = json.loads(manifest.read_text())["image_id"]
    subprocess.run([sys.executable,ctx.source_path("dps-install/scripts/prepare-ldap-fresh.py"),
                    "--root",ctx.runtime_root,"--image",image],check=True)
    raise SystemExit(0)
info = json.loads(identity.read_text())
if info["endpoint"] != f"ldaps://{ctx.settings['host_ip']}:{ctx.settings['ldap_port']}":
    raise SystemExit("Recorded LDAP endpoint conflicts with deployment.yaml; preserve existing identity")
required = [l/"compose.yaml", l/"slapd.conf", l/"bootstrap.ldif", l/"password-hashes.json",
            l/"admin.password",l/"bind.password",l/"user.password",l/"noaccess.password",
            l/"tls/server.key",l/"tls/server.crt",l/"tls/ca.crt",l/"deployment.json"]
if any(not f.is_file() for f in required):
    raise SystemExit("Recorded LDAP identity/configuration is incomplete; restore missing material")
account = json.loads((c/"dps-access.json").read_text())
if account["username"] != info["username"] or account["password"] != info.get("user_password",info.get("password")):
    raise SystemExit("LDAP and DPS account identities differ; refusing password replacement")
compose = yaml.safe_load((l/"compose.yaml").read_text())
service = next(v for v in compose["services"].values() if v.get("container_name")==ctx.settings["ldap_container"])
recorded = json.loads((l/"deployment.json").read_text())
image = recorded.get("image_id") or service["image"]
actual = subprocess.run(["docker","image","inspect",image],capture_output=True,text=True,check=True)
if json.loads(actual.stdout)[0]["Id"] != image:
    raise SystemExit("Recorded LDAP image differs; preserve rather than change it")
def openssl(*args):
    return subprocess.check_output(["openssl",*map(str,args)],stderr=subprocess.PIPE)
if openssl("pkey","-in",l/"tls/server.key","-pubout") != openssl("x509","-in",l/"tls/server.crt","-noout","-pubkey"):
    raise SystemExit("LDAP server certificate/key mismatch")
openssl("verify","-CAfile",l/"tls/ca.crt","-purpose","sslserver","-verify_ip",ctx.settings["host_ip"],l/"tls/server.crt")
openssl("x509","-in",l/"tls/server.crt","-noout","-checkend","86400")
secret(l/"dps-ldap-bind-secret.yaml","dps-ldap-bind",ctx.settings["namespace"],{"bind-password":info["bind_password"]})
secret(l/"dps-ldap-ca-secret.yaml","dps-ldap-ca",ctx.settings["namespace"],{"ca.crt":(l/"tls/ca.crt").read_text()})
print("Recorded LDAP service, password hashes, directory and TLS identity preserved; stable Secrets prepared.")
