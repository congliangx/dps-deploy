#!/usr/bin/env python3
"""Install one independent Lab component after the shared host prerequisites.

Uses deployment.yaml, pinned component artifacts and the existing fresh producer.
Creates private runtime inputs and starts only this component's Docker Compose
project. Does not install Kubernetes/DPS, apply Secrets, rotate retained
identities, adopt an earlier manual deployment, or write BMC power settings.
Choose the component/manual route separately from the full Lab bootstrap.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess


def execute(args, stdin=None):
    result = subprocess.run([str(x) for x in args], input=stdin, text=True,
                            capture_output=True, timeout=1800)
    if result.returncode:
        # Captured commands can contain credentials/configuration: never echo them.
        raise RuntimeError("Command failed: " + str(args[0]) + " " + str(args[1]))
    return result.stdout


def no_links(root, path):
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise RuntimeError("Symlink in component input; preserve and review: " + str(parent))
        if parent == root:
            return
    raise RuntimeError("Component input leaves runtime root")


def component_spec(ctx, component):
    s, root = ctx.settings, ctx.runtime_root
    c = root / "dps-install/config"
    cfg = c / ("postgresql" if component == "postgresql" else "ldap")
    artifacts = json.loads(ctx.source_path("dps-install/config/artifact-sources.json").read_text())
    if component == "bmc":
        cfg = root / "hardware-sim/runtime"
        return dict(
            marker=c / "bmc-bootstrap.json", compose=cfg / "compose.yaml",
            producer="prepare-bmc-fresh.py", project=s["bmc_project"],
            containers={s["bmc_container"]: "simulator", s["proxy_container"]: "proxy"},
            networks={s["bmc_network"]: "bmc"}, ports=list(range(s["bmc_start_port"], s["bmc_start_port"] + 72)),
            port_owner=s["proxy_container"],
            identity={"host_ip": s["host_ip"], "host_name": s["host_name"], "start_port": s["bmc_start_port"],
                      "namespace": s["namespace"], "agent_id": s["agent_id"], "topology_name": s["topology_name"],
                      "container_name": s["bmc_container"], "proxy_name": s["proxy_container"], "network_name": s["bmc_network"]},
            paths=[cfg, c / "topology-4rack-dps09.json", c / "bmc-credentials.json", c / "bmc-endpoints.csv", c / "simulator-ca.crt",
                   c / "bmc-shared-secret.yaml", c / "bmc-ca-secret.yaml"],
            required=[cfg / x for x in ("authority/ca.key", "authority/ca.crt", "tls/tls.key", "tls/tls.crt",
                                        "compose.yaml", "config.yaml", "nginx.conf", "nodes.json")] +
                     [c / "topology-4rack-dps09.json", c / "bmc-endpoints.csv", c / "bmc-credentials.json", c / "simulator-ca.crt", c / "bmc-shared-secret.yaml", c / "bmc-ca-secret.yaml"],
            credentials=c / "bmc-credentials.json")
    if component == "postgresql":
        image = next(x["image_digest"] for x in artifacts["images"] if x["name"] == "postgresql-server-and-migration-client")
        return dict(
            marker=cfg / "deployment.json", compose=cfg / "compose.yaml", producer="prepare-postgresql.py",
            project=s["pg_project"], containers={s["pg_container"]: "postgresql"},
            networks={s["pg_network"]: "database"}, ports=[s["pg_port"]], port_owner=s["pg_container"],
            identity={"host_ip": s["host_ip"], "host_name": s["host_name"], "port": s["pg_port"],
                      "container_name": s["pg_container"], "network_name": s["pg_network"],
                      "subnet": s["pg_subnet"], "pod_cidr": s["pod_cidr"], "namespace": s["namespace"]},
            image=image, paths=[cfg, root / "dps-install/data/postgresql", c / "postgresql-credentials.json",
                                c / "postgresql-ca.crt", c / "postgresql-secret.yaml", c / "postgresql-ca-secret.yaml"],
            required=[cfg / x for x in ("compose.yaml", "private/ca.key", "tls/ca.crt", "tls/server.key",
                                        "tls/server.crt", "secrets/admin-password", "secrets/dps-password",
                                        "postgresql.conf", "pg_hba.conf", "10-init-dps.sql")] +
                     [c / "postgresql-credentials.json", c / "postgresql-ca.crt", c / "postgresql-secret.yaml", c / "postgresql-ca-secret.yaml"],
            credentials=c / "postgresql-credentials.json")
    return dict(
        marker=cfg / "deployment.json", compose=cfg / "compose.yaml", producer="prepare-ldap-fresh.py",
        project=s["ldap_project"], containers={s["ldap_container"]: "openldap"},
        networks={s["ldap_project"] + "_default": "default"}, ports=[s["ldap_port"]], port_owner=s["ldap_container"],
        identity={"host": s["host_ip"], "host_name": s["host_name"], "port": s["ldap_port"],
                  "container_name": s["ldap_container"], "namespace": s["namespace"], "base_dn": "dc=dps,dc=lab"},
        paths=[cfg, root / "dps-install/data/ldap", c / "dps-access.json"],
        required=[cfg / x for x in ("credentials.json", "password-hashes.json", "admin.password", "bind.password",
                                    "user.password", "noaccess.password", "slapd.conf", "bootstrap.ldif", "compose.yaml",
                                    "tls/ca.crt", "tls/server.key", "tls/server.crt", "dps-client.key", "dps-client.crt",
                                    "dps-ldap-bind-secret.yaml", "dps-ldap-ca-secret.yaml", "dps-ldap-client-tls-secret.yaml")] +
                 [c / "dps-access.json"], credentials=cfg / "credentials.json")


def input_ownership(ctx, component, spec):
    root = ctx.runtime_root
    for path in [spec["marker"], *spec["paths"], *spec["required"]]:
        no_links(root, path)
    owned = spec["marker"].is_file()
    if owned:
        state = json.loads(spec["marker"].read_text())
        if component == "bmc":
            valid = state == spec["identity"]
        elif component == "postgresql":
            valid = (state.get("format_version") == 1 and state.get("parameters") == spec["identity"]
                     and state.get("image") == spec["image"])
        else:
            identity = dict(state.get("identity") or {})
            identity.pop("image_id", None)
            valid = (state.get("producer") == spec["producer"] and state.get("root") == str(root)
                     and identity == spec["identity"])
        if not valid:
            raise RuntimeError("Recorded component identity/parameters differ; use its maintenance guide or a new instance.")
        for path in spec["required"]:
            if not path.is_file():
                raise RuntimeError("Retained component input is incomplete; restore: " + str(path))
    else:
        for path in spec["paths"]:
            # LDAP artifact acquisition can be resumed before identity generation.
            if component == "ldap" and path == spec["marker"].parent and path.is_dir():
                existing = [item for item in path.iterdir() if item.name != "runtime-build.json"]
                occupied = bool(existing)
            else:
                occupied = path.exists() and (not path.is_dir() or any(path.iterdir()))
            if occupied:
                raise RuntimeError("Existing unowned component configuration/data; use its maintenance guide or a clean runtime.")
    return owned


def expected_container(ctx, spec, service):
    import yaml
    config = yaml.safe_load(spec["compose"].read_text())["services"][service]
    mounts = set()
    for volume in config.get("volumes", []):
        source, destination, *mode = volume.split(":")
        mounts.add((str(Path(source).resolve()), destination, "ro" not in mode))
    ports = set()
    for entry in config.get("ports", []):
        address, published, target = entry.split(":")
        def expand(value):
            ends = value.split("-")
            return range(int(ends[0]), int(ends[-1]) + 1)
        published_range, target_range = list(expand(published)), list(expand(target))
        if len(published_range) != len(target_range):
            raise RuntimeError("Invalid retained Compose port range.")
        ports.update((str(t) + "/tcp", address, str(p)) for p, t in zip(published_range, target_range))
    return config["image"], mounts, ports


def docker_ownership(ctx, component, spec, owned):
    s = ctx.settings
    if execute(["docker", "info", "--format", "{{.OSType}}"]).strip() != "linux":
        raise RuntimeError("A Linux Docker daemon is required.")
    version = execute(["docker", "compose", "version", "--short"]).strip().lstrip("v")
    if tuple(int(x) for x in version.split(".")[:2]) < (2, 18):
        raise RuntimeError("Docker Compose >= 2.18 is required for up --wait.")
    all_names = set(execute(["docker", "ps", "-a", "--format", "{{.Names}}"]).splitlines())
    members = execute(["docker", "ps", "-a", "--filter", "label=com.docker.compose.project=" + spec["project"],
                       "--format", "{{.Names}}"]).splitlines()
    if set(members) - set(spec["containers"]):
        raise RuntimeError("Compose project contains unrelated containers; choose another project.")
    existing = {}
    for name, service in spec["containers"].items():
        if name not in all_names:
            continue
        obj = json.loads(execute(["docker", "container", "inspect", name]))[0]
        labels = obj.get("Config", {}).get("Labels") or {}
        config_files = labels.get("com.docker.compose.project.config_files", "").split(",")
        mounts = [m.get("Source", "") for m in obj.get("Mounts", []) if m.get("Type") == "bind"]
        if (not owned or labels.get("com.docker.compose.project") != spec["project"]
                or labels.get("com.docker.compose.service") != service
                or config_files != [str(spec["compose"])]
                or not mounts or any(not Path(m).is_relative_to(ctx.runtime_root) for m in mounts)):
            raise RuntimeError("Existing Docker container is not owned by these runtime inputs: " + name)
        image, expected_mounts, expected_ports = expected_container(ctx, spec, service)
        observed_mounts = {(str(Path(m["Source"]).resolve()), m["Destination"], m.get("RW", True))
                           for m in obj.get("Mounts", []) if m.get("Type") == "bind"}
        observed_ports = {(target, binding["HostIp"], binding["HostPort"])
                          for target, bindings in (obj.get("HostConfig", {}).get("PortBindings") or {}).items()
                          for binding in bindings or []}
        if (obj.get("Config", {}).get("Image") != image or observed_mounts != expected_mounts
                or observed_ports != expected_ports
                or set(obj.get("NetworkSettings", {}).get("Networks") or {}) != set(spec["networks"])):
            raise RuntimeError("Retained container image/mount/port/network differs; use its maintenance guide: " + name)
        image_info = json.loads(execute(["docker", "image", "inspect", image]))[0]
        if obj.get("Image") != image_info["Id"]:
            raise RuntimeError("Retained container image identity differs: " + name)
        existing[name] = obj
    networks = execute(["docker", "network", "ls", "--format", "{{.Name}}"]).splitlines()
    for name in networks:
        obj = json.loads(execute(["docker", "network", "inspect", name]))[0]
        if name in spec["networks"]:
            labels = obj.get("Labels") or {}
            members = obj.get("Containers") or {}
            if component == "postgresql" and {x.get("Subnet") for x in obj.get("IPAM", {}).get("Config") or []} != {s["pg_subnet"]}:
                raise RuntimeError("Existing PostgreSQL network subnet differs; preserve and review.")
            if (not owned or labels.get("com.docker.compose.project") != spec["project"]
                    or labels.get("com.docker.compose.network") != spec["networks"][name]
                    or any(item.get("Name") not in spec["containers"] for item in members.values())):
                raise RuntimeError("Existing Docker network is not owned by this component: " + name)
        elif component == "postgresql":
            desired = ipaddress.ip_network(s["pg_subnet"])
            for item in obj.get("IPAM", {}).get("Config") or []:
                subnet = item.get("Subnet")
                if subnet and ipaddress.ip_network(subnet).version == 4 and desired.overlaps(ipaddress.ip_network(subnet)):
                    raise RuntimeError("PostgreSQL subnet overlaps another Docker network; choose another pg_subnet.")
    owner = existing.get(spec["port_owner"], {})
    bindings = owner.get("HostConfig", {}).get("PortBindings") or {}
    retained_ports = {int(b["HostPort"]) for values in bindings.values() for b in values or []
                      if b.get("HostIp") == s["host_ip"] and b.get("HostPort", "").isdigit()}
    for port in spec["ports"]:
        if owner.get("State", {}).get("Running") and port in retained_ports:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((s["host_ip"], port))
            except OSError:
                raise RuntimeError("Configured host IP/port is unavailable: " + str(port))


def preflight(ctx, component, spec):
    if os.geteuid() != 0:
        raise RuntimeError("Run as root after installing the shared host prerequisites.")
    for binary in (("docker", "openssl", "curl") if component == "bmc" else ("docker", "openssl")):
        if not shutil.which(binary):
            raise RuntimeError("Install shared host prerequisites first: missing " + binary)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", spec["project"]):
        raise RuntimeError("Invalid Compose project in deployment.yaml")
    if component == "postgresql":
        subnet = ipaddress.ip_network(ctx.settings["pg_subnet"])
        if (ipaddress.ip_address(ctx.settings["host_ip"]) in subnet or
                any(subnet.overlaps(ipaddress.ip_network(ctx.settings[key])) for key in ("pod_cidr", "service_cidr"))):
            raise RuntimeError("PostgreSQL subnet overlaps the host/Pod/Service network; choose another pg_subnet.")
    owned = input_ownership(ctx, component, spec)
    docker_ownership(ctx, component, spec, owned)
    return owned


def install(ctx, component):
    from bootstrap_common import private
    spec = component_spec(ctx, component)
    preflight(ctx, component, spec)  # Reject historical/manual instances before any mutation.
    lock_dir = ctx.runtime_path("dps-install/config")
    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = lock_dir / ".component-install.lock"
    no_links(ctx.runtime_root, lock_path)
    with lock_path.open("a") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preflight(ctx, component, spec)
        common = ["--config", ctx.config_path, "--runtime-root", ctx.runtime_root]
        execute([sys.executable, ctx.source_path("dps-install/scripts/download-artifacts.py"),
                 *common, "--component", component])
        extra = []
        if component == "ldap":
            build = json.loads(ctx.runtime_path("dps-install/config/ldap/runtime-build.json").read_text())
            extra = ["--image", build["image_id"]]
        execute([sys.executable, ctx.source_path("dps-install/scripts/" + spec["producer"]), *common, *extra])
        compose = ["docker", "compose", "-p", spec["project"], "-f", spec["compose"]]
        execute([*compose, "config", "--quiet"])
        execute([*compose, "up", "-d", "--wait", "--wait-timeout", "300"])
        s = ctx.settings
        if component == "bmc":
            execute(["docker", "exec", s["proxy_container"], "nginx", "-t"])
            execute(["curl", "--fail", "--silent", "--show-error", "--max-time", "30", "--cacert",
                     ctx.runtime_path("dps-install/config/simulator-ca.crt"),
                     "https://" + s["host_ip"] + ":" + str(s["bmc_start_port"]) + "/readyz"])
        elif component == "postgresql":
            sql = "SELECT 1; SELECT count(*) FROM pg_database WHERE datname IN ('dps','dps_prs_config','dps_prs_config_staged','dps_prs_controller');"
            result = execute(["docker", "exec", "--user", "postgres", s["pg_container"], "psql",
                              "--no-psqlrc", "-At", "-v", "ON_ERROR_STOP=1", "-d", "postgres", "-c", sql])
            if result.strip().splitlines() != ["1", "4"]:
                raise RuntimeError("PostgreSQL read-only database initialization check failed.")
        else:
            info = json.loads(spec["credentials"].read_text())
            execute(["docker", "exec", "--env", "LDAPTLS_REQCERT=demand", "--env",
                     "LDAPTLS_CACERT=/ldap/config/tls/ca.crt", s["ldap_container"], "ldapwhoami", "-x", "-H",
                     "ldaps://127.0.0.1:1636", "-D", info["bind_dn"], "-y", "/ldap/config/bind.password"])
            result = execute(["docker", "exec", "--env", "LDAPTLS_REQCERT=demand", "--env",
                              "LDAPTLS_CACERT=/ldap/config/tls/ca.crt", s["ldap_container"], "ldapsearch", "-LLL", "-x", "-H",
                              "ldaps://127.0.0.1:1636", "-D", info["bind_dn"], "-y", "/ldap/config/bind.password",
                              "-b", info["authorization_group_dn"], "-s", "base", "(objectClass=groupOfNames)", "member"])
            if "member: " + info["user_dn"] not in result.splitlines():
                raise RuntimeError("LDAP read-only authorization group check failed.")
        report = ctx.runtime_path("verification/reports/" + component + "-installation.json")
        private(report, {"component": component, "installed": True, "compose": str(spec["compose"]),
                         "credentials_file": str(spec["credentials"]), "runtime_root": str(ctx.runtime_root),
                         "secret_yaml_applied": False, "kubernetes_installed": False, "dps_installed": False,
                         "private_values_printed": False, "bmc_power_writes": False})
        print(json.dumps({"component": component, "installed": True, "compose": str(spec["compose"]),
                          "credentials_file": str(spec["credentials"]), "report": str(report),
                          "secret_yaml_applied": False, "dps_installed": False, "private_values_printed": False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--component", required=True, choices=("bmc", "postgresql", "ldap"))
    parser.add_argument("--config", "--deployment-config", help="Public deployment.yaml configuration")
    parser.add_argument("--runtime-root", "--root", help="Override runtime_root from the configuration")
    parser.add_argument("--source-root", help="Override the source checkout")
    if any(x in ("--help", "-h") for x in sys.argv[1:]):
        parser.parse_args()  # No context imports, Docker calls or runtime writes for help.
        return 0
    if sum(x == "--component" or x.startswith("--component=") for x in sys.argv[1:]) != 1:
        parser.error("Do not override --component on a component-specific entrypoint.")
    from deployment_context import context_from_cli
    ctx = context_from_cli()
    args = parser.parse_args()
    os.umask(0o077)
    install(ctx, args.component)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired) as error:
        print("Component installation stopped: " + str(error), file=sys.stderr)
        raise SystemExit(1)
