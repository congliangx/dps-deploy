#!/usr/bin/env python3
"""One public deployment configuration; source inputs and runtime outputs stay separate."""
import sys
sys.dont_write_bytecode = True
import argparse, hashlib, ipaddress, json, os, re, shlex
from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass(frozen=True)
class DeploymentContext:
    source_root: Path
    runtime_root: Path
    settings: dict
    config_path: Path
    config_sha256: str

    def source_path(self, relative):
        return self._path(self.source_root, relative)

    def runtime_path(self, relative):
        return self._path(self.runtime_root, relative)

    @staticmethod
    def _path(base, relative):
        relative = Path(relative)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Context paths must be relative without parent traversal")
        return base / relative

    def env(self):
        s = self.settings
        env = {"DPS_SOURCE_ROOT": str(self.source_root), "DPS_RUNTIME_ROOT": str(self.runtime_root),
               "DPS_DEPLOYMENT_CONFIG": str(self.config_path), "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONPYCACHEPREFIX": str(self.runtime_root / "cache/python"),
               "PYTHONPATH": str(self.source_root / "dps-install/scripts"),
               "DPS_CONTEXT_SETTINGS": json.dumps({"config_path":str(self.config_path),"config_sha256":self.config_sha256,"source_root":str(self.source_root),"settings":s}, separators=(",",":"))}
        for key, value in s.items():
            if isinstance(value, (str, int, float)):
                env["DPS_" + key.upper()] = str(value)
        c = self.runtime_path("dps-install/config")
        env.update(KUBECONFIG=str(c/"kubernetes/kubeconfig.yaml"),
                   DPS_KUBE_CONTEXT=s["kube_context"], DPS_KUBE_NODE=s["host_name"].lower(),
                   DPSCTL_HOST=s["api_name"], DPSCTL_PORT="443", DPSCTL_CA_CERT_PATH=str(c/"tls/ca.crt"),
                   DPSCTL_CREDENTIALS_PATH=str(c/"dpsctl/credentials.yaml"),
                   DPSCTL_LOG_FILE=str(self.runtime_path("verification/logs/dpsctl.log")),
                   HELM_CONFIG_HOME=str(c/"helm"),
                   HELM_CACHE_HOME=str(self.runtime_path("dps-install/data/helm-cache")),
                   HELM_DATA_HOME=str(self.runtime_path("dps-install/data/helm-data")))
        return env


def load_context(source_root=None, runtime_root=None, config_path=None, overrides=None):
    source = Path(source_root or os.environ.get("DPS_SOURCE_ROOT") or Path(__file__).resolve().parents[2]).expanduser().resolve()
    config = Path(config_path or (os.environ.get("DPS_DEPLOYMENT_CONFIG") if source_root is None else None) or source/"deployment.yaml").expanduser().resolve()
    config_raw = config.read_bytes()
    config_sha256 = hashlib.sha256(config_raw).hexdigest()
    s = yaml.safe_load(config_raw)
    if not isinstance(s, dict):
        raise ValueError("deployment.yaml must be a flat mapping")
    defaults = dict(s)
    s = dict(s)
    # One public, validated context is inherited by subprocesses; unrelated DPS_ env is ignored.
    inherited_valid = False
    inherited = os.environ.get("DPS_CONTEXT_SETTINGS")
    if inherited:
        inherited = json.loads(inherited)
        if (inherited.get("config_path") == str(config) and inherited.get("source_root") == str(source)
            and inherited.get("config_sha256") == config_sha256):
            inherited_valid = True
            s.update({k:v for k,v in inherited.get("settings", {}).items() if k in defaults})
    for k, v in (overrides or {}).items():
        if v is not None: s[k] = v
    for key, suffix in (("pg_project","postgresql"),("ldap_project","ldap"),("bmc_project","bmc")):
        if s["instance_prefix"] != defaults["instance_prefix"] and s.get(key) == defaults.get(key) and (overrides or {}).get(key) is None:
            s[key] = s["instance_prefix"] + "-" + suffix
        s.setdefault(key, s["instance_prefix"] + "-" + suffix)
    runtime = Path(runtime_root or (os.environ.get("DPS_RUNTIME_ROOT") if inherited_valid else None) or s["runtime_root"]).expanduser().resolve()
    if runtime == source or source in runtime.parents or runtime in source.parents:
        raise ValueError("Runtime and source directories must be separate without nesting")
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", str(runtime)):
        raise ValueError("Runtime path must contain only letters, digits, /, _, . and -")
    ipaddress.IPv4Address(s["host_ip"])
    for key in ("host_name", "api_name", "ui_name"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,253}", s[key]): raise ValueError("Invalid " + key)
    for key in ("namespace", "release", "agent_id", "instance_prefix"):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", s[key]): raise ValueError("Invalid " + key)
    for key in ("pg_port", "ldap_port", "bmc_start_port", "kube_api_port"):
        s[key] = int(s[key])
        if not 1 <= s[key] <= 65535: raise ValueError("Invalid " + key)
    if s["bmc_start_port"] + 71 > 65535: raise ValueError("BMC range exceeds 65535")
    for key in ("pg_subnet", "pod_cidr", "service_cidr"):
        s[key] = str(ipaddress.IPv4Network(s[key], strict=True))
    s.update(runtime_root=str(runtime), root=str(runtime), source_root=str(source),
             pg_container=s["instance_prefix"]+"-postgresql", ldap_container=s["instance_prefix"]+"-openldap",
             bmc_container=s["instance_prefix"]+"-gb300-bmc", proxy_container=s["instance_prefix"]+"-gb300-bmc-proxy",
             pg_network=s["instance_prefix"]+"-postgresql-net", bmc_network=s["instance_prefix"]+"-bmc-net",
             fullname=s["release"] if "dps" in s["release"] else s["release"]+"-dps",
             kubeconfig=str(runtime/"dps-install/config/kubernetes/kubeconfig.yaml"))
    s.setdefault("resolv_conf", "/run/systemd/resolve/resolv.conf" if Path("/run/systemd/resolve/resolv.conf").exists() else "/etc/resolv.conf")
    return DeploymentContext(source, runtime, s, config, config_sha256)


def context_from_cli():
    """Consume shared overrides, leaving entrypoint-specific arguments in sys.argv."""
    parser = argparse.ArgumentParser(add_help=False,allow_abbrev=False)
    parser.add_argument("--source-root")
    parser.add_argument("--root", "--runtime-root", dest="runtime_root")
    parser.add_argument("--deployment-config", "--config", dest="config_path")
    for key in ("host_ip", "host_name", "interface", "namespace", "release", "agent_id", "api_name", "ui_name", "instance_prefix", "pg_subnet", "pod_cidr", "service_cidr", "kube_context", "topology_name", "pg_project", "ldap_project", "bmc_project", "k3s_version", "helm_version", "kubectl_version", "dps_version"):
        parser.add_argument("--"+key.replace("_", "-"))
    for key in ("pg_port", "ldap_port", "bmc_start_port", "kube_api_port"):
        parser.add_argument("--"+key.replace("_", "-"), type=int)
    args, remaining = parser.parse_known_args()
    sys.argv[1:] = remaining
    fields = vars(args); source=fields.pop("source_root"); runtime=fields.pop("runtime_root"); config=fields.pop("config_path")
    ctx = load_context(source_root=source, runtime_root=runtime, config_path=config, overrides=fields)
    os.environ.update(ctx.env())
    return ctx

if __name__ == "__main__":
    shell = "--shell" in sys.argv
    if shell: sys.argv.remove("--shell")
    ctx = context_from_cli()
    if shell:
        print("\n".join("export "+k+"="+shlex.quote(v) for k,v in ctx.env().items()))
    else:
        print(json.dumps({"source_root":str(ctx.source_root),"runtime_root":str(ctx.runtime_root),"settings":ctx.settings}))
