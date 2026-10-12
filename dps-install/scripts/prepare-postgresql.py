#!/usr/bin/env python3
"""Generate an independent PostgreSQL 17 deployment without starting services.

Requires only Python's standard library and openssl. Repeated preparation keeps
passwords and signing identities. Existing incomplete identities fail closed.
"""
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

IMAGE = "postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3"
DATABASES = ("dps", "dps_prs_config", "dps_prs_config_staged", "dps_prs_controller")
POSTGRES_UID = 999
POSTGRES_GID = 999
SECRET_NAME = "dps-postgresql"
CA_SECRET_NAME = "dps-postgresql-ca"

class PreparationError(Exception):
    pass

def openssl(*args):
    result = subprocess.run(["openssl", *map(str, args)], capture_output=True, text=True)
    if result.returncode:
        raise PreparationError("OpenSSL verification or generation failed: " + str(args[0]))
    return result.stdout

def put(path, text, mode=0o600, owner=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep bind-mounted inodes and mtimes stable when generated content is unchanged.
    if path.exists() and path.is_file() and path.read_bytes() == text.encode():
        path.chmod(mode)
        if owner is not None:
            try:
                os.chown(path, *owner)
            except PermissionError as exc:
                raise PreparationError("Cannot grant the PostgreSQL UID access to its private files.") from exc
        return
    temporary = path.with_name("." + path.name + ".tmp-" + secrets.token_hex(6))
    try:
        temporary.write_text(text)
        temporary.chmod(mode)
        if owner is not None:
            try:
                os.chown(temporary, *owner)
            except PermissionError as exc:
                raise PreparationError("Preparing PostgreSQL private files requires root or the PostgreSQL UID.") from exc
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()

def put_json(path, value, mode=0o600):
    put(path, json.dumps(value, indent=2) + "\n", mode)

def verify_pair(key, certificate, ca=None, host_ip=None, host_name=None):
    if key.exists() != certificate.exists():
        raise PreparationError("Incomplete certificate/key pair: " + str(certificate))
    if not key.exists():
        return False
    if openssl("x509", "-in", certificate, "-pubkey", "-noout") != openssl("pkey", "-in", key, "-pubout"):
        raise PreparationError("Certificate/private-key identity mismatch: " + str(certificate))
    openssl("x509", "-in", certificate, "-noout", "-checkend", "86400")
    if ca is None:
        openssl("verify", "-CAfile", certificate, certificate)
        if "CA:TRUE" not in openssl("x509", "-in", certificate, "-noout", "-ext", "basicConstraints"):
            raise PreparationError("Existing certificate is not a signing CA.")
    else:
        openssl("verify", "-CAfile", ca, "-purpose", "sslserver", "-verify_ip", host_ip, certificate)
        openssl("verify", "-CAfile", ca, "-purpose", "sslserver", "-verify_hostname", host_name, certificate)
        openssl("verify", "-CAfile", ca, "-purpose", "sslserver", "-verify_hostname", "localhost", certificate)
    return True

def secret(namespace, name, values):
    return {
        "apiVersion": "v1", "kind": "Secret",
        "metadata": {"name": name, "namespace": namespace,
                     "labels": {"app.kubernetes.io/part-of": "dps-prerequisites"}},
        "type": "Opaque",
        "data": {k: base64.b64encode(v).decode() for k, v in values.items()},
    }

def parse():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--host-ip", default="10.6.131.43")
    parser.add_argument("--host-name", default="L20-12")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--container-name", default="dps-postgresql")
    parser.add_argument("--network-name", default="dps-postgresql-net")
    parser.add_argument("--subnet", default="172.30.90.0/24")
    parser.add_argument("--pod-cidr", default="10.42.0.0/16")
    parser.add_argument("--namespace", default="dps")
    args = parser.parse_args()
    args.root = args.root.expanduser().resolve()
    try:
        args.host_ip = str(ipaddress.ip_address(args.host_ip))
        args.subnet = str(ipaddress.ip_network(args.subnet, strict=True))
        args.pod_cidr = str(ipaddress.ip_network(args.pod_cidr, strict=True))
    except ValueError as exc:
        raise PreparationError("Invalid IP address or canonical network CIDR.") from exc
    if not 1 <= args.port <= 65535:
        raise PreparationError("Port must be in 1..65535.")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", args.host_name):
        raise PreparationError("Host name must be a DNS name.")
    for name in (args.container_name, args.network_name):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
            raise PreparationError("Invalid Docker container/network name.")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", args.namespace):
        raise PreparationError("Invalid Kubernetes namespace.")
    if not shutil.which("openssl"):
        raise PreparationError("openssl is required.")
    return args

def prepare(args):
    os.umask(0o077)
    config_root = args.root / "dps-install/config"
    config = config_root / "postgresql"
    private = config / "private"
    tls = config / "tls"
    password_dir = config / "secrets"
    data = args.root / "dps-install/data/postgresql"
    credentials_path = config_root / "postgresql-credentials.json"
    state_path = config / "deployment.json"
    ca_key = private / "ca.key"
    ca_cert = tls / "ca.crt"
    server_key = tls / "server.key"
    server_cert = tls / "server.crt"
    parameters = {
        "host_ip": args.host_ip, "host_name": args.host_name, "port": args.port,
        "container_name": args.container_name, "network_name": args.network_name,
        "subnet": args.subnet, "pod_cidr": args.pod_cidr, "namespace": args.namespace,
    }
    existing_data = data.exists() and any(data.iterdir())
    reused_identity = credentials_path.exists()
    # Inspect all existing identities before generating or replacing any files.
    ca_exists = verify_pair(ca_key, ca_cert)
    if server_key.exists() or server_cert.exists():
        if not ca_exists:
            raise PreparationError("Existing server identity has no complete signing CA.")
        verify_pair(server_key, server_cert, ca_cert, args.host_ip, args.host_name)
    if existing_data and not credentials_path.exists():
        raise PreparationError("Existing PostgreSQL data without credentials; refusing new passwords.")
    if state_path.exists():
        old = json.loads(state_path.read_text())
        if old.get("parameters") != parameters or old.get("image") != IMAGE:
            raise PreparationError("Prepared PostgreSQL parameters differ; refusing an implicit reconfiguration.")
        if (not ca_exists or not server_cert.exists()
            or old.get("ca_sha256") != hashlib.sha256(ca_cert.read_bytes()).hexdigest()
            or old.get("server_certificate_sha256") != hashlib.sha256(server_cert.read_bytes()).hexdigest()):
            raise PreparationError("TLS identity differs from the prepared manifest; refusing implicit replacement.")
    if credentials_path.exists():
        credentials = json.loads(credentials_path.read_text())
        expected = {"host": args.host_ip, "port": args.port, "database": "dps",
                    "username": "dps", "admin_username": "postgres",
                    "sslmode": "verify-full", "secret_name": SECRET_NAME, "secret_key": "password"}
        if any(credentials.get(k) != v for k, v in expected.items()):
            raise PreparationError("Existing PostgreSQL credential identity or endpoint differs.")
        for key, filename in (("password", "dps-password"), ("admin_password", "admin-password")):
            if not isinstance(credentials.get(key), str) or len(credentials[key]) < 32:
                raise PreparationError("Existing PostgreSQL password is incomplete or weak.")
            path = password_dir / filename
            if not path.exists() or path.read_text() != credentials[key]:
                raise PreparationError("Existing credential/password-file pair is incomplete or inconsistent.")
        if existing_data and (not ca_exists or not server_key.exists()):
            raise PreparationError("Existing database data requires its original complete TLS identity.")
    else:
        if any((password_dir / f).exists() for f in ("dps-password", "admin-password")):
            raise PreparationError("Password files exist without their credentials manifest.")
        credentials = {
            "host": args.host_ip, "port": args.port, "database": "dps", "username": "dps",
            "password": secrets.token_urlsafe(36), "admin_username": "postgres",
            "admin_password": secrets.token_urlsafe(36), "sslmode": "verify-full",
            "sslrootcert": str(config_root / "postgresql-ca.crt"),
            "secret_name": SECRET_NAME, "secret_key": "password",
        }
    for directory in (config_root, config, private, password_dir):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    tls.mkdir(parents=True, exist_ok=True)
    tls.chmod(0o755)
    data.mkdir(parents=True, exist_ok=True)
    data.chmod(0o700)
    try:
        os.chown(data, POSTGRES_UID, POSTGRES_GID)
    except PermissionError as exc:
        raise PreparationError("Cannot grant the PostgreSQL UID access to its data directory.") from exc
    if not ca_exists:
        openssl("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", ca_key)
        ca_key.chmod(0o600)
        openssl("req", "-x509", "-new", "-key", ca_key, "-sha256", "-days", "3650",
                "-out", ca_cert, "-subj", "/CN=DPS PostgreSQL Lab CA/O=DPS Lab",
                "-addext", "basicConstraints=critical,CA:TRUE",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    if not server_key.exists():
        extension = tls / "server.ext"
        put(extension, "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n"
            f"subjectAltName=IP:{args.host_ip},DNS:{args.host_name},DNS:localhost,IP:127.0.0.1\n", 0o644)
        openssl("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", server_key)
        openssl("req", "-new", "-key", server_key, "-out", tls / "server.csr",
                "-subj", f"/CN={args.host_name}/O=DPS Lab")
        openssl("x509", "-req", "-in", tls / "server.csr", "-CA", ca_cert, "-CAkey", ca_key,
                "-set_serial", str(secrets.randbits(128)), "-days", "825", "-sha256",
                "-extfile", extension, "-out", server_cert)
    verify_pair(ca_key, ca_cert)
    verify_pair(server_key, server_cert, ca_cert, args.host_ip, args.host_name)
    ca_key.chmod(0o600)
    server_key.chmod(0o600)
    try:
        os.chown(server_key, POSTGRES_UID, POSTGRES_GID)
    except PermissionError as exc:
        raise PreparationError("Cannot grant the PostgreSQL UID access to its private server key.") from exc
    ca_cert.chmod(0o644)
    server_cert.chmod(0o644)
    for key, filename in (("password", "dps-password"), ("admin_password", "admin-password")):
        put(password_dir / filename, credentials[key], owner=(POSTGRES_UID, POSTGRES_GID))
    credentials["sslrootcert"] = str(config_root / "postgresql-ca.crt")
    put_json(credentials_path, credentials)
    public_ca = ca_cert.read_bytes()
    put(config_root / "postgresql-ca.crt", public_ca.decode(), 0o644)
    put_json(config_root / "postgresql-secret.yaml", secret(args.namespace, SECRET_NAME,
             {"password": credentials["password"].encode(), "database-password": credentials["password"].encode()}))
    put_json(config_root / "postgresql-ca-secret.yaml", secret(args.namespace, CA_SECRET_NAME, {"ca.crt": public_ca}))
    host_prefix = "/32" if ipaddress.ip_address(args.host_ip).version == 4 else "/128"
    hba = "# DPS and PRS use role dps over TLS/SCRAM only.\n" \
          "local all postgres peer\nlocal all all scram-sha-256\n" \
          "hostnossl all all 0.0.0.0/0 reject\nhostnossl all all ::/0 reject\n"
    sources = (args.host_ip + host_prefix, args.pod_cidr, args.subnet)
    for source in sources:
        hba += f"hostssl dps dps {source} scram-sha-256\n"
    hba += "# BEGIN DPS PRS TLS DATABASES\n"
    hba += "# PRS uses the same non-superuser role and trusted client networks.\n"
    for source in sources:
        hba += f"hostssl {','.join(DATABASES[1:])} dps {source} scram-sha-256\n"
    hba += "# END DPS PRS TLS DATABASES\n"
    hba += "host all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n"
    put(config / "pg_hba.conf", hba, 0o644)
    put(config / "postgresql.conf",
        "listen_addresses = '*'\nport = 5432\nmax_connections = 200\nshared_buffers = '256MB'\n"
        "password_encryption = 'scram-sha-256'\nhba_file = '/etc/postgresql/config/pg_hba.conf'\nssl = on\n"
        "ssl_cert_file = '/etc/postgresql/tls/server.crt'\nssl_key_file = '/etc/postgresql/tls/server.key'\n"
        "ssl_ca_file = '/etc/postgresql/tls/ca.crt'\nssl_min_protocol_version = 'TLSv1.2'\n"
        "log_connections = on\nlog_disconnections = on\nlog_statement = 'none'\n"
        "log_min_error_statement = 'panic'\n", 0o644)
    sql = ("-- Runs only on first initialization of an empty PGDATA.\n"
           "\\set dps_password " + chr(96) + "cat /run/secrets/dps-password" + chr(96) + "\n"
           "CREATE ROLE dps WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'dps_password';\n"
           "\\unset dps_password\n")
    for database in DATABASES:
        sql += (f"CREATE DATABASE {database} OWNER dps;\nREVOKE ALL ON DATABASE {database} FROM PUBLIC;\n"
                f"GRANT CONNECT ON DATABASE {database} TO dps;\n\\connect {database}\n"
                "ALTER SCHEMA public OWNER TO dps;\nREVOKE ALL ON SCHEMA public FROM PUBLIC;\n"
                "GRANT USAGE, CREATE ON SCHEMA public TO dps;\n")
    put(config / "10-init-dps.sql", sql, 0o644)
    binding = args.host_ip if ":" not in args.host_ip else "[" + args.host_ip + "]"
    # JSON is valid YAML and avoids an additional Python YAML dependency.
    compose = {
        "services": {"postgresql": {
            "image": IMAGE, "container_name": args.container_name,
            "restart": "unless-stopped", "shm_size": "512m",
            "environment": {
                "POSTGRES_USER": "postgres", "POSTGRES_DB": "postgres",
                "POSTGRES_PASSWORD_FILE": "/run/secrets/admin-password",
                "POSTGRES_INITDB_ARGS": "--auth-local=peer --auth-host=scram-sha-256",
                "PGDATA": "/var/lib/postgresql/data/pgdata",
            },
            "command": ["postgres", "-c", "config_file=/etc/postgresql/config/postgresql.conf"],
            "ports": [f"{binding}:{args.port}:5432"],
            "volumes": [
                f"{data}:/var/lib/postgresql/data",
                f"{config / 'postgresql.conf'}:/etc/postgresql/config/postgresql.conf:ro",
                f"{config / 'pg_hba.conf'}:/etc/postgresql/config/pg_hba.conf:ro",
                f"{tls}:/etc/postgresql/tls:ro",
                f"{password_dir / 'admin-password'}:/run/secrets/admin-password:ro",
                f"{password_dir / 'dps-password'}:/run/secrets/dps-password:ro",
                f"{config / '10-init-dps.sql'}:/docker-entrypoint-initdb.d/10-init-dps.sql:ro",
            ],
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U postgres -d postgres"],
                "interval": "5s", "timeout": "5s", "retries": 20, "start_period": "15s",
            },
            "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
            "networks": ["database"],
        }},
        "networks": {"database": {
            "name": args.network_name, "ipam": {"config": [{"subnet": args.subnet}]}
        }},
    }
    put_json(config / "compose.yaml", compose)
    put_json(state_path, {
        "format_version": 1, "parameters": parameters, "image": IMAGE,
        "postgresql_version": "17.11", "postgres_uid": POSTGRES_UID, "postgres_gid": POSTGRES_GID,
        "database_names": list(DATABASES), "ca_sha256": hashlib.sha256(public_ca).hexdigest(),
        "server_certificate_sha256": hashlib.sha256(server_cert.read_bytes()).hexdigest(),
    })
    return {
        "status": "prepared", "root": str(args.root), "reused_identity": reused_identity,
        "host": args.host_ip, "port": args.port, "container_name": args.container_name,
        "network_name": args.network_name, "image": IMAGE, "database_names": list(DATABASES),
        "username": "dps", "sslmode": "verify-full", "compose": str(config / "compose.yaml"),
        "credentials": str(credentials_path), "ca_certificate": str(config_root / "postgresql-ca.crt"),
        "password_secret": str(config_root / "postgresql-secret.yaml"),
        "ca_secret": str(config_root / "postgresql-ca-secret.yaml"), "deployment_manifest": str(state_path),
    }

def main():
    try:
        result = prepare(parse())
    except (PreparationError, OSError, ValueError, KeyError) as exc:
        print("PostgreSQL preparation refused: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
