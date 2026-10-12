#!/usr/bin/env python3
"""Small, secret-safe helpers shared by the cold-install entrypoints."""
import base64, hashlib, ipaddress, json, os, re, subprocess
from pathlib import Path
import yaml

def repo_root(value=None):
    p = Path(value).resolve() if value else Path(__file__).resolve().parents[2]
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", str(p)):
        raise ValueError("Repository path must contain only letters, digits, /, _, . and -")
    return p

def private(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    text = value if isinstance(value, str) else (
        yaml.safe_dump(value, sort_keys=False) if path.suffix in (".yaml", ".yml") else
        json.dumps(value, indent=2) + "\n")
    temp = path.with_name("." + path.name + ".tmp")
    temp.write_text(text); temp.chmod(0o600); temp.replace(path)

def command(args, data=None, capture=True):
    result = subprocess.run([str(a) for a in args], input=data, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode:
        # Never echo stderr/stdout from commands which can contain secret data.
        raise RuntimeError(f"Command failed ({result.returncode}): {args[0]} {args[1] if len(args)>1 else ''}")
    return result.stdout if capture else ""

def pair(folder, name, subject, ca=None, sans=None, purpose="serverAuth"):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True); folder.chmod(0o700)
    key, crt = folder/(name+".key"), folder/(name+".crt")
    if key.exists() != crt.exists():
        raise RuntimeError("Incomplete certificate pair: " + str(folder/name))
    if not key.exists():
        command(["openssl","genrsa","-out",key,"3072"])
        if ca is None:
            command(["openssl","req","-new","-x509","-sha256","-days","3650","-key",key,
                     "-out",crt,"-subj","/CN="+subject,"-addext","basicConstraints=critical,CA:TRUE",
                     "-addext","keyUsage=critical,keyCertSign,cRLSign"])
        else:
            csr, ext = folder/(name+".csr"), folder/(name+".ext")
            ext.write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
                           "extendedKeyUsage="+purpose+"\nsubjectAltName="+",".join(sans or [])+"\n")
            command(["openssl","req","-new","-key",key,"-out",csr,"-subj","/CN="+subject])
            command(["openssl","x509","-req","-in",csr,"-CA",ca[1],"-CAkey",ca[0],"-CAcreateserial",
                     "-out",crt,"-days","825","-sha256","-extfile",ext])
    key.chmod(0o600); crt.chmod(0o644)
    if command(["openssl","pkey","-in",key,"-pubout"]) != command(["openssl","x509","-in",crt,"-noout","-pubkey"]):
        raise RuntimeError("Certificate/key mismatch: "+str(crt))
    command(["openssl","x509","-in",crt,"-noout","-checkend","86400"])
    if ca:
        command(["openssl","verify","-CAfile",ca[1],"-purpose",
                 "sslclient" if purpose=="clientAuth" else "sslserver",crt])
    for san in sans or []:
        kind, value = san.split(":",1)
        command(["openssl","x509","-in",crt,"-noout","-checkip" if kind=="IP" else "-checkhost",value])
    return key, crt

def require_existing_identity(marker, files):
    if Path(marker).exists():
        missing = [str(path) for path in files if not Path(path).is_file()]
        if missing:
            raise RuntimeError("Recorded identity is incomplete; restore the missing private input before rerunning: " + missing[0])

def secret(path, name, namespace, data, labels=None):
    metadata = {"name":name,"namespace":namespace}
    if labels: metadata["labels"]=labels
    path = Path(path)
    if path.exists():
        previous = yaml.safe_load(path.read_text())
        old_data = {key:base64.b64decode(value).decode() for key,value in previous.get("data", {}).items()}
        old_data.update(previous.get("stringData", {}))
        if (previous.get("metadata", {}).get("name") != name or
            previous.get("metadata", {}).get("namespace") != namespace or old_data != data):
            raise RuntimeError("Existing Secret input differs from its identity; preserve and review: " + str(path))
    private(path, {"apiVersion":"v1","kind":"Secret","metadata":metadata,"type":"kubernetes.io/tls" if "tls.key" in data and "tls.crt" in data else "Opaque","stringData":data})

def bind_settings(path, desired, identity_exists=False):
    path = Path(path)
    if path.exists():
        if json.loads(path.read_text()) != desired:
            raise RuntimeError("Bootstrap parameters changed; preserve the existing identity: "+str(path))
    elif identity_exists:
        raise RuntimeError("Existing unrecorded identity; use its maintenance workflow or a clean repository directory.")
    else: private(path, desired)

def validate_host(ip, hostname):
    ipaddress.IPv4Address(ip)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,62}", hostname):
        raise ValueError("Invalid host name")
