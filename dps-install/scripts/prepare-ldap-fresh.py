#!/usr/bin/env python3
"""Prepare an independent first-install LDAP identity without migrating existing DPS."""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import yaml

PRODUCER = "prepare-ldap-fresh.py"
BASE_DN = "dc=dps,dc=lab"
LDAP_DNS = "ldap.dps.lab"


def command(args):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError("Required command failed: " + args[0])
    return result.stdout


def openssl(*args):
    return command(["openssl", *map(str, args)])


def write(path, value, public=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if isinstance(value, dict):
        value = json.dumps(value, indent=2) + "\n" if path.suffix == ".json" else yaml.safe_dump(value, sort_keys=False)
    path.write_text(value)
    path.chmod(0o644 if public else 0o600)


def reject_link(path):
    if path.is_symlink():
        raise RuntimeError("Refusing symbolic link for managed input: " + str(path))


def pair(key, cert, purpose=None, ca=None):
    if key.exists() != cert.exists() or not key.exists():
        raise RuntimeError("Missing or partial certificate pair: " + str(cert))
    if openssl("pkey", "-in", key, "-pubout") != openssl("x509", "-in", cert, "-pubkey", "-noout"):
        raise RuntimeError("Certificate does not match its private key: " + str(cert))
    openssl("x509", "-in", cert, "-noout", "-checkend", "86400")
    if ca:
        args = ["verify", "-CAfile", ca]
        if purpose:
            args += ["-purpose", purpose]
        openssl(*args, cert)


def issue(key, cert, csr, ext, ca, ca_key, cn, usage, sans=None):
    openssl("genrsa", "-out", key, "3072")
    openssl("req", "-new", "-key", key, "-out", csr, "-subj", "/CN=" + cn)
    contents = "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
    contents += "extendedKeyUsage=" + usage + "\n"
    if sans:
        contents += "subjectAltName=" + ",".join(sans) + "\n"
    write(ext, contents)
    openssl("x509", "-req", "-in", csr, "-CA", ca, "-CAkey", ca_key,
            "-set_serial", str(secrets.randbits(120) or 1), "-out", cert,
            "-days", "364", "-sha256", "-extfile", ext)
    key.chmod(0o600)
    cert.chmod(0o644)


def ssha(password):
    salt = secrets.token_bytes(16)
    return "{SSHA}" + base64.b64encode(hashlib.sha1(password.encode() + salt).digest() + salt).decode()


def secret(name, namespace, values):
    return {
        "apiVersion": "v1", "kind": "Secret",
        "metadata": {"name": name, "namespace": namespace}, "type": "Opaque",
        "data": {key: base64.b64encode(value).decode() for key, value in values.items()},
    }


def expected_identity(args, image_id):
    return {
        "host": args.host_ip, "host_name": args.host_name, "port": args.port,
        "container_name": args.container_name, "namespace": args.namespace,
        "image_id": image_id, "base_dn": BASE_DN,
    }


def validate_existing(args, root, cfg, data, image_id):
    manifest_path, credentials_path = cfg / "deployment.json", cfg / "credentials.json"
    if not credentials_path.exists():
        return False
    if not manifest_path.exists():
        raise RuntimeError("Existing LDAP credentials lack first-install ownership metadata; refusing changes")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("root") != str(root):
        raise RuntimeError("Existing LDAP inputs belong to another root; refusing implicit relocation")
    if manifest.get("producer") != PRODUCER:
        raise RuntimeError("Existing LDAP configuration is not owned by this first-install producer; refusing changes")
    if manifest.get("identity") != expected_identity(args, image_id):
        raise RuntimeError("Existing LDAP identity or image differs from requested parameters; refusing changes")
    info = json.loads(credentials_path.read_text())
    account_path = root / "dps-install/config/dps-access.json"
    required = [
        account_path, cfg / "password-hashes.json", cfg / "admin.password", cfg / "bind.password",
        cfg / "user.password", cfg / "noaccess.password", cfg / "slapd.conf",
        cfg / "bootstrap.ldif", cfg / "compose.yaml", cfg / "tls/ca.crt",
        cfg / "tls/server.key", cfg / "tls/server.crt", cfg / "dps-client.key", cfg / "dps-client.crt",
        cfg / "dps-ldap-bind-secret.yaml", cfg / "dps-ldap-ca-secret.yaml",
        cfg / "dps-ldap-client-tls-secret.yaml",
    ]
    for path in required:
        reject_link(path)
        if not path.is_file():
            raise RuntimeError("Existing LDAP input set is incomplete: " + str(path))
    account = json.loads(account_path.read_text())
    if info.get("username") != "dps-lab" or account.get("username") != "dps-lab":
        raise RuntimeError("Unexpected existing LDAP account identity")
    if (info.get("password") != account.get("password") or
            info.get("user_password") != account.get("password") or
            info.get("allowgroup") != "dcpower-users" or account.get("authentication") != "ldap"):
        raise RuntimeError("Existing LDAP and DPS account credentials differ")
    if info.get("base_dn") != BASE_DN or info.get("endpoint") != manifest.get("endpoint"):
        raise RuntimeError("Existing LDAP directory identity differs")
    for filename, key in [
        ("admin.password", "admin_password"), ("bind.password", "bind_password"),
        ("user.password", "password"), ("noaccess.password", "noaccess_password"),
    ]:
        if not isinstance(info.get(key), str) or len(info[key]) < 24:
            raise RuntimeError("Existing LDAP credential does not meet bootstrap requirements")
        if (cfg / filename).read_text() != info[key]:
            raise RuntimeError("Existing LDAP password file differs from saved credentials: " + filename)
    compose = yaml.safe_load((cfg / "compose.yaml").read_text())
    service = compose.get("services", {}).get("openldap", {})
    if (compose.get("name") != args.container_name or service.get("container_name") != args.container_name or
            service.get("image") != image_id or service.get("ports") != [f"{args.host_ip}:{args.port}:1636"] or
            service.get("volumes") != [f"{cfg}:/ldap/config:ro", f"{data}:/var/lib/ldap"]):
        raise RuntimeError("Existing LDAP Compose identity or mounts differ; refusing changes")
    saved_hashes = json.loads((cfg / "password-hashes.json").read_text())
    for key in ["admin_password", "bind_password", "password", "noaccess_password"]:
        value = saved_hashes.get(key, "")
        try:
            raw = base64.b64decode(value.removeprefix("{SSHA}"), validate=True)
        except ValueError:
            raise RuntimeError("Invalid saved LDAP password hash")
        if not value.startswith("{SSHA}") or len(raw) <= 20 or hashlib.sha1(info[key].encode() + raw[20:]).digest() != raw[:20]:
            raise RuntimeError("Saved LDAP password hash differs from retained credentials")
    pair(cfg / "tls/server.key", cfg / "tls/server.crt", "sslserver", cfg / "tls/ca.crt")
    pair(cfg / "dps-client.key", cfg / "dps-client.crt", "sslclient", cfg / "tls/ca.crt")
    openssl("verify", "-CAfile", cfg / "tls/ca.crt", "-verify_ip", args.host_ip, cfg / "tls/server.crt")
    openssl("verify", "-CAfile", cfg / "tls/ca.crt", "-verify_ip", "127.0.0.1", cfg / "tls/server.crt")
    openssl("verify", "-CAfile", cfg / "tls/ca.crt", "-verify_hostname", "localhost", cfg / "tls/server.crt")
    if manifest["ca_source"] == "independent":
        reject_link(cfg / "tls/ca.key")
        pair(cfg / "tls/ca.key", cfg / "tls/ca.crt")
    elif manifest["ca_source"] == "project":
        project = root / "dps-install/config/tls"
        pair(project / "ca.key", project / "ca.crt")
        if (project / "ca.crt").read_bytes() != (cfg / "tls/ca.crt").read_bytes():
            raise RuntimeError("Project CA differs from the retained LDAP issuer")
    else:
        raise RuntimeError("Unknown saved LDAP issuer source")
    # Validate saved private Secret payloads in memory; do not print their values.
    for filename, name, payload in [
        ("dps-ldap-bind-secret.yaml", "dps-ldap-bind", {"bind-password": info["bind_password"].encode()}),
        ("dps-ldap-ca-secret.yaml", "dps-ldap-ca", {"ca.crt": (cfg / "tls/ca.crt").read_bytes()}),
        ("dps-ldap-client-tls-secret.yaml", "dps-ldap-client-tls", {
            "tls.crt": (cfg / "dps-client.crt").read_bytes(), "tls.key": (cfg / "dps-client.key").read_bytes()}),
    ]:
        existing = yaml.safe_load((cfg / filename).read_text())
        if existing != secret(name, args.namespace, payload):
            raise RuntimeError("Existing LDAP Secret differs from retained identity: " + filename)
    return True


def prepare(args):
    root = args.root.expanduser().resolve()
    cfg = root / "dps-install/config/ldap"
    data = root / "dps-install/data/ldap"
    account_path = root / "dps-install/config/dps-access.json"
    for path in [cfg, cfg / "tls", data, account_path, cfg / "credentials.json", cfg / "deployment.json"]:
        reject_link(path)
    image = json.loads(command(["docker", "image", "inspect", args.image]))[0]
    image_id = image["Id"]
    if image.get("Config", {}).get("Entrypoint") != ["/usr/local/bin/ldap-entrypoint"]:
        raise RuntimeError("Image does not expose the independent LDAP build recipe entrypoint")
    if validate_existing(args, root, cfg, data, image_id):
        return {"status": "reused", "root": str(root), "endpoint": f"ldaps://{args.host_ip}:{args.port}",
                "image_id": image_id, "namespace": args.namespace, "changed": False,
                "credentials_file": str(cfg / "credentials.json"), "private_values_printed": False}
    if data.exists() and any(data.iterdir()):
        raise RuntimeError("LDAP data exists without retained credentials; refusing new identities")
    private_existing = [account_path, cfg / "password-hashes.json", cfg / "admin.password", cfg / "bind.password",
                        cfg / "user.password", cfg / "noaccess.password", cfg / "tls/server.key",
                        cfg / "tls/server.crt", cfg / "tls/ca.crt", cfg / "tls/ca.key",
                        cfg / "dps-client.key", cfg / "dps-client.crt", cfg / "deployment.json",
                        cfg / "slapd.conf", cfg / "bootstrap.ldif",
                        cfg / "dps-ldap-bind-secret.yaml", cfg / "dps-ldap-ca-secret.yaml",
                        cfg / "dps-ldap-client-tls-secret.yaml"]
    for path in private_existing:
        reject_link(path)
        if path.exists():
            raise RuntimeError("Unowned or partial LDAP identity input already exists: " + str(path))
    project = root / "dps-install/config/tls"
    for path in [project, project / "ca.key", project / "ca.crt"]:
        reject_link(path)
    if (project / "ca.key").exists() != (project / "ca.crt").exists():
        raise RuntimeError("Project CA key/certificate pair is incomplete")
    ca_source = "project" if (project / "ca.key").exists() else "independent"
    if ca_source == "project":
        pair(project / "ca.key", project / "ca.crt")
    cfg.mkdir(parents=True, exist_ok=True, mode=0o700)
    cfg.chmod(0o700)
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    data.chmod(0o700)
    (root / "dps-install/data/ldap-backups").mkdir(parents=True, exist_ok=True, mode=0o700)
    endpoint = f"ldaps://{args.host_ip}:{args.port}"
    info = {
        "endpoint": endpoint, "host": args.host_ip, "host_name": args.host_name, "port": args.port,
        "dns": LDAP_DNS, "base_dn": BASE_DN, "user_base_dn": "ou=users," + BASE_DN,
        "group_base_dn": "ou=groups," + BASE_DN, "admin_dn": "cn=admin," + BASE_DN,
        "admin_password": secrets.token_urlsafe(36),
        "bind_dn": "uid=dps-bind,ou=services," + BASE_DN, "bind_password": secrets.token_urlsafe(36),
        "username": "dps-lab", "user_dn": "uid=dps-lab,ou=users," + BASE_DN,
        "password": secrets.token_urlsafe(32), "authorization_group": "dcpower-users",
        "authorization_group_dn": "cn=dcpower-users,ou=groups," + BASE_DN,
        "noaccess_username": "dps-noaccess", "noaccess_user_dn": "uid=dps-noaccess,ou=users," + BASE_DN,
        "noaccess_password": secrets.token_urlsafe(36),
    }
    # Keep the legacy password field and explicit aliases for direct-LDAP bootstrap consumers.
    info["user_password"] = info["password"]
    info["allowgroup"] = info["authorization_group"]
    hashes = {key: ssha(info[key]) for key in ["admin_password", "bind_password", "password", "noaccess_password"]}
    with tempfile.TemporaryDirectory(prefix=".ldap-fresh-", dir=cfg.parent) as temporary:
        stage = Path(temporary)
        tls = stage / "tls"
        tls.mkdir(mode=0o700)
        if ca_source == "project":
            shutil.copyfile(project / "ca.crt", tls / "ca.crt")
            ca_key = project / "ca.key"
        else:
            ca_key = tls / "ca.key"
            openssl("genrsa", "-out", ca_key, "3072")
            openssl("req", "-new", "-x509", "-sha256", "-days", "730", "-key", ca_key,
                    "-out", tls / "ca.crt", "-subj", "/CN=DPS-LDAP-" + args.host_name + "-Lab-CA",
                    "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
            ca_key.chmod(0o600)
        (tls / "ca.crt").chmod(0o644)
        sans = sorted({"DNS:" + LDAP_DNS, "DNS:" + args.host_name, "DNS:" + args.host_name.lower(),
                       "DNS:localhost", "IP:" + args.host_ip, "IP:127.0.0.1"})
        issue(tls / "server.key", tls / "server.crt", tls / "server.csr", tls / "server.ext",
              tls / "ca.crt", ca_key, LDAP_DNS, "serverAuth", sans)
        issue(stage / "dps-client.key", stage / "dps-client.crt", stage / "dps-client.csr",
              stage / "dps-client.ext", tls / "ca.crt", ca_key, "dps-ldap-client", "clientAuth")
        pair(tls / "server.key", tls / "server.crt", "sslserver", tls / "ca.crt")
        pair(stage / "dps-client.key", stage / "dps-client.crt", "sslclient", tls / "ca.crt")
        for address in [args.host_ip, "127.0.0.1"]:
            openssl("verify", "-CAfile", tls / "ca.crt", "-verify_ip", address, tls / "server.crt")
        openssl("verify", "-CAfile", tls / "ca.crt", "-verify_hostname", "localhost", tls / "server.crt")
        write(stage / "credentials.json", info)
        write(stage / "password-hashes.json", hashes)
        for filename, key in [("admin.password", "admin_password"), ("bind.password", "bind_password"),
                              ("user.password", "password"), ("noaccess.password", "noaccess_password")]:
            write(stage / filename, info[key])
        conf = f"""include /etc/ldap/schema/core.schema
include /etc/ldap/schema/cosine.schema
include /etc/ldap/schema/nis.schema
include /etc/ldap/schema/inetorgperson.schema
pidfile /run/slapd/slapd.pid
argsfile /run/slapd/slapd.args
modulepath /usr/lib/ldap
moduleload back_mdb
TLSCACertificateFile /run/ldap-config/ca.crt
TLSCertificateFile /run/ldap-config/server.crt
TLSCertificateKeyFile /run/ldap-config/server.key
TLSProtocolMin 3.3
disallow bind_anon
require authc
security simple_bind=128
database mdb
maxsize 1073741824
suffix "{BASE_DN}"
rootdn "{info['admin_dn']}"
rootpw {hashes['admin_password']}
directory /var/lib/ldap
index objectClass eq
index uid,cn eq
index member eq
access to attrs=userPassword
 by anonymous auth
 by self auth
 by * none
access to *
 by dn.exact="{info['bind_dn']}" read
 by self read
 by * none
"""
        write(stage / "slapd.conf", conf)
        seed = f"""dn: {BASE_DN}
objectClass: top
objectClass: dcObject
objectClass: organization
dc: dps
o: DPS Independent Lab

dn: ou=users,{BASE_DN}
objectClass: organizationalUnit
ou: users

dn: ou=groups,{BASE_DN}
objectClass: organizationalUnit
ou: groups

dn: ou=services,{BASE_DN}
objectClass: organizationalUnit
ou: services

dn: {info['bind_dn']}
objectClass: account
objectClass: simpleSecurityObject
uid: dps-bind
userPassword: {hashes['bind_password']}

dn: {info['user_dn']}
objectClass: inetOrgPerson
objectClass: posixAccount
uid: dps-lab
cn: DPS Lab Administrator
sn: Administrator
uidNumber: 10000
gidNumber: 10000
homeDirectory: /nonexistent
loginShell: /usr/sbin/nologin
userPassword: {hashes['password']}

dn: {info['noaccess_user_dn']}
objectClass: inetOrgPerson
objectClass: posixAccount
uid: dps-noaccess
cn: DPS Unprivileged Verification User
sn: Verification
uidNumber: 10002
gidNumber: 10000
homeDirectory: /nonexistent
loginShell: /usr/sbin/nologin
userPassword: {hashes['noaccess_password']}

dn: {info['authorization_group_dn']}
objectClass: groupOfNames
cn: dcpower-users
member: {info['user_dn']}

"""
        write(stage / "bootstrap.ldif", seed)
        compose = {
            "name": args.container_name,
            "services": {"openldap": {
                "image": image_id, "pull_policy": "never", "container_name": args.container_name,
                "restart": "unless-stopped", "read_only": True, "security_opt": ["no-new-privileges:true"],
                "cap_drop": ["ALL"], "cap_add": ["CHOWN", "FOWNER", "SETUID", "SETGID", "DAC_OVERRIDE"],
                "ports": [f"{args.host_ip}:{args.port}:1636"],
                "volumes": [f"{cfg}:/ldap/config:ro", f"{data}:/var/lib/ldap"],
                "tmpfs": ["/run:rw,nosuid,nodev,mode=755", "/tmp:rw,nosuid,nodev,mode=1777"],
                "environment": {"LDAPTLS_CACERT": "/ldap/config/tls/ca.crt", "LDAPTLS_REQCERT": "demand"},
                "healthcheck": {"test": ["CMD", "ldapwhoami", "-x", "-H", "ldaps://127.0.0.1:1636",
                                       "-D", info["bind_dn"], "-y", "/ldap/config/bind.password"],
                                "interval": "10s", "timeout": "5s", "retries": 12, "start_period": "10s"},
                "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
            }},
        }
        write(stage / "compose.yaml", compose)
        for filename, name, payload in [
            ("dps-ldap-bind-secret.yaml", "dps-ldap-bind", {"bind-password": info["bind_password"].encode()}),
            ("dps-ldap-ca-secret.yaml", "dps-ldap-ca", {"ca.crt": (tls / "ca.crt").read_bytes()}),
            ("dps-ldap-client-tls-secret.yaml", "dps-ldap-client-tls", {
                "tls.crt": (stage / "dps-client.crt").read_bytes(), "tls.key": (stage / "dps-client.key").read_bytes()}),
        ]:
            write(stage / filename, secret(name, args.namespace, payload))
        account = {"username": info["username"], "password": info["password"], "role": "admin",
                   "authentication": "ldap", "authenticator": "ldap", "ldap_dn": info["user_dn"],
                   "ldap_endpoint": endpoint, "note": "Fresh independent LDAP identity; admin comes from dcpower-users."}
        write(stage / "dps-access.json", account)
        manifest = {
            "producer": PRODUCER, "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "identity": expected_identity(args, image_id), "root": str(root), "image": args.image,
            "image_id": image_id, "repo_digests": image.get("RepoDigests", []),
            "endpoint": endpoint, "base_dn": BASE_DN, "user_base_dn": info["user_base_dn"],
            "group_base_dn": info["group_base_dn"], "bind_dn": info["bind_dn"], "user_dn": info["user_dn"],
            "authorization_group": info["authorization_group"], "ca_source": ca_source,
            "ca_path": str(cfg / "tls/ca.crt"), "client_cert_path": str(cfg / "dps-client.crt"),
            "client_key_path": str(cfg / "dps-client.key"),
            "ca_sha256": hashlib.sha256((tls / "ca.crt").read_bytes()).hexdigest(),
            "data_path": str(data), "old_runtime_archive_required": False, "legacy_migration_state_required": False,
            "secret_names": ["dps-ldap-bind", "dps-ldap-ca", "dps-ldap-client-tls"],
        }
        write(stage / "deployment.json", manifest)
        # Commit only after every new input is prepared and verified; ownership manifest is last.
        for path in sorted(stage.rglob("*")):
            if not path.is_file() or path.name in ["deployment.json", "dps-access.json"]:
                continue
            destination = cfg / path.relative_to(stage)
            reject_link(destination)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.replace(path, destination)
        os.replace(stage / "dps-access.json", account_path)
        os.replace(stage / "deployment.json", cfg / "deployment.json")
    return {
        "status": "created", "root": str(root), "endpoint": endpoint, "image_id": image_id,
        "namespace": args.namespace, "changed": True, "ca_source": ca_source,
        "credentials_file": str(cfg / "credentials.json"), "compose_file": str(cfg / "compose.yaml"),
        "secret_names": ["dps-ldap-bind", "dps-ldap-ca", "dps-ldap-client-tls"], "private_values_printed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--host-ip", default="10.6.131.43")
    parser.add_argument("--host-name", default="L20-12")
    parser.add_argument("--port", type=int, default=1636)
    parser.add_argument("--container-name", default="dps-openldap")
    parser.add_argument("--namespace", default="dps")
    parser.add_argument("--image", default="dps-openldap:2.6.10-debian13",
                        help="Existing image/tag/ID built from the independent LDAP recipe; no historical ID required")
    args = parser.parse_args()
    os.umask(0o077)
    if ipaddress.ip_address(args.host_ip).version != 4:
        parser.error("--host-ip must be an IPv4 address")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", args.host_name):
        parser.error("--host-name must be a DNS-style hostname")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", args.container_name):
        parser.error("--container-name must be a lower-case Compose-compatible name")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", args.namespace):
        parser.error("--namespace must be a Kubernetes namespace name")
    try:
        result = prepare(args)
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "error", "error": str(error), "private_values_printed": False}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
