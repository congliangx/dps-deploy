#!/usr/bin/env python3
"""Verify a freshly bootstrapped DPS stack without deployment or hardware writes."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import http.cookiejar
import json
import math
import os
from pathlib import Path
import re
import secrets
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import yaml


def status_ok(value):
    return isinstance(value, dict) and value.get("status", {}).get("ok") is True


def parse_json(text):
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character in "[{":
            try:
                return decoder.raw_decode(text[index:])[0]
            except ValueError:
                pass
    raise ValueError("Command did not return a JSON response")


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class Verification:
    def __init__(self, root):
        self.root = root.resolve()
        self.cfg = self.root / "dps-install/config"
        self.settings = json.loads((self.cfg / "bootstrap-settings.json").read_text())
        if Path(self.settings["root"]).resolve() != self.root:
            raise RuntimeError("bootstrap-settings.json belongs to a different root")
        required = ["host_ip", "namespace", "release", "agent_id", "api_name", "ui_name", "bmc_start_port",
                    "pg_container", "ldap_container", "bmc_container", "proxy_container", "kubeconfig", "kube_context"]
        if any(not self.settings.get(key) for key in required):
            raise RuntimeError("bootstrap-settings.json lacks required target fields")
        self.ns, self.release = self.settings["namespace"], self.settings["release"]
        self.kubeconfig = Path(self.settings["kubeconfig"])
        if not self.kubeconfig.is_absolute():
            self.kubeconfig = self.root / self.kubeconfig
        if not self.kubeconfig.resolve().is_relative_to(self.root):
            raise RuntimeError("Verifier requires the copied project kubeconfig under --root")
        self.account = json.loads((self.cfg / "dps-access.json").read_text())
        self.bmc_credentials = json.loads((self.cfg / "bmc-credentials.json").read_text())
        self.values = yaml.safe_load((self.cfg / "values.yaml").read_text())
        self.private = []
        for path in [self.cfg / "dps-access.json", self.cfg / "bmc-credentials.json",
                     self.cfg / "postgresql-credentials.json", self.cfg / "ldap/credentials.json",
                     self.cfg / "prs/s3-credentials.json"]:
            if path.exists():
                def collect(value):
                    if isinstance(value, dict):
                        for key, item in value.items():
                            if isinstance(item, str) and re.search(r"(?:^|_)(?:password|passwd|access_token|refresh_token|admin_access_key_id|access_key_id|admin_secret_access_key|secret_access_key)$", key, re.I):
                                self.private.append(item)
                            else:
                                collect(item)
                    elif isinstance(value, list):
                        for item in value:
                            collect(item)
                collect(json.loads(path.read_text()))
        self.checks, self.nodes, self.pods, self.services = [], [], [], []
        self.tools = {}
        for name in ["kubectl", "helm", "dpsctl"]:
            local = self.root / "dps-install/packages/tools/bin" / name
            self.tools[name] = str(local) if local.is_file() else name
        self.env = os.environ.copy()
        for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
                    "DPSCTL_CLIENT_CERT_PATH", "DPSCTL_CLIENT_KEY_PATH"]:
            self.env.pop(key, None)
        self.env.update({
            "KUBECONFIG": str(self.kubeconfig), "DPSCTL_HOST": self.settings["api_name"],
            "DPSCTL_PORT": "443", "DPSCTL_CA_CERT_PATH": str(self.cfg / "tls/ca.crt"),
            "DPSCTL_AUTH_MODE": "jwt", "DPSCTL_INSECURE": "false", "DPSCTL_INSECURE_TLS_SKIP_VERIFY": "false",
        })
        self.kbase = [self.tools["kubectl"], "--kubeconfig", str(self.kubeconfig),
                      "--context", self.settings["kube_context"], "-n", self.ns]
        self.work, self.credentials = None, None

    def clean(self, text):
        text = str(text)
        for value in sorted(set(self.private), key=len, reverse=True):
            if value:
                text = text.replace(value, "[REDACTED]")
        text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED_JWT]", text)
        text = re.sub(r"\{(?:SSHA|SHA|SSHA512|CRYPT)\}[A-Za-z0-9+/=$.]{20,}", "[REDACTED_HASH]", text)
        text = re.sub(r"(https?://)[^/\s:@]+:[^/\s@]+@", r"\1[REDACTED_USERINFO]@", text)
        return text

    def safe(self, value):
        if isinstance(value, dict):
            return {key: self.safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.safe(item) for item in value]
        return self.clean(value) if isinstance(value, str) else value

    def check(self, name, passed, evidence=None):
        self.checks.append({"name": name, "passed": bool(passed), "evidence": self.safe(evidence or {})})

    def attempt(self, name, function):
        try:
            function()
        except Exception as error:
            self.check(name, False, {"error": self.clean(error)[:1600]})

    def run(self, args, data=None, allow_failure=False, env=None, timeout=60):
        result = subprocess.run(args, input=data, text=True, capture_output=True,
                                env=env or self.env, timeout=timeout)
        if result.returncode and not allow_failure:
            raise RuntimeError(self.clean(result.stderr[-1400:] or result.stdout[-1400:]) or "Command failed")
        return result

    def kube(self, resource):
        return json.loads(self.run(self.kbase + ["get", resource, "-o", "json"]).stdout)

    def cli_result(self, args, password=None, credentials=None, allow_failure=False):
        env = self.env.copy()
        env.update({"DPSCTL_CREDENTIALS_PATH": str(credentials or self.credentials),
                    "DPSCTL_LOG_FILE": str(self.work / "dpsctl.log"), "XDG_CONFIG_HOME": str(self.work / "xdg")})
        result = self.run([self.tools["dpsctl"], "--no-retry", "--grpc-timeout", "25s"] + list(args),
                          data=password, allow_failure=allow_failure, env=env)
        try:
            payload = parse_json(result.stdout)
        except ValueError:
            if not allow_failure:
                raise
            payload = {}
        if not allow_failure and isinstance(payload, dict) and "status" in payload and not status_ok(payload):
            raise RuntimeError(self.clean(payload.get("status", {})))
        return result, payload

    def cli(self, *args):
        return self.cli_result(args)[1]

    def pod_for(self, suffix):
        candidates = [pod for pod in self.pods if re.search(re.escape(suffix) + r"(?:-[a-z0-9]+){1,3}$", pod["metadata"]["name"])
                      and pod.get("status", {}).get("phase") == "Running"]
        if len(candidates) != 1:
            raise RuntimeError("Expected one running Pod for " + suffix)
        return candidates[0]

    def service_for(self, suffix):
        candidates = [service for service in self.services if service["metadata"]["name"].endswith("-" + suffix)]
        if len(candidates) != 1:
            raise RuntimeError("Expected one Service for " + suffix)
        return candidates[0]

    def pod_code(self, pod, container, code):
        output = self.run(self.kbase + ["exec", "-i", pod["metadata"]["name"], "-c", container, "--", "python3", "-"], code).stdout
        for line in reversed(output.splitlines()):
            if line.startswith("{"):
                return json.loads(line)
        raise RuntimeError("Pod verification did not produce a result")

    def http(self, url, context=None):
        handlers = [urllib.request.ProxyHandler({})]
        if context:
            handlers.append(urllib.request.HTTPSHandler(context=context))
        opener = urllib.request.build_opener(*handlers)
        with opener.open(url, timeout=20) as response:
            return response.status, response.read()

    def docker(self):
        for role in ["pg", "ldap", "bmc", "proxy"]:
            name = self.settings[role + "_container"]
            item = json.loads(self.run(["docker", "inspect", "--type", "container", name]).stdout)[0]
            state = item["State"]
            health = state.get("Health", {}).get("Status", "not_configured")
            # The simulator may lack a Docker healthcheck; all 72 endpoints are checked independently.
            passed = state.get("Running") and not state.get("Restarting") and not state.get("OOMKilled")
            if role != "bmc" or health != "not_configured":
                passed = passed and health == "healthy"
            self.check("docker-" + role + "-running-health", passed,
                       {"container": name, "status": state.get("Status"), "health": health,
                        "restart_count": item.get("RestartCount"), "healthcheck_configured": health != "not_configured"})

    def bmc(self):
        nodes = json.loads((self.root / "hardware-sim/runtime/nodes.json").read_text())
        expected_ports = set(range(int(self.settings["bmc_start_port"]), int(self.settings["bmc_start_port"]) + 72))
        endpoints = [urlsplit(node["bmc_url"]) for node in nodes]
        canonical = {(endpoint.scheme, endpoint.hostname, endpoint.port) for endpoint in endpoints}
        ports = {endpoint.port for endpoint in endpoints}
        self.check("bmc-node-map", len(nodes) == 72 and len(canonical) == 72 and ports == expected_ports,
                   {"nodes": len(nodes), "unique_endpoints": len(canonical), "port_range_matches_settings": ports == expected_ports})
        context = ssl.create_default_context(cafile=str(self.cfg / "simulator-ca.crt"))
        basic = base64.b64encode((self.bmc_credentials["username"] + ":" + self.bmc_credentials["password"]).encode()).decode()
        def verify(node):
            result = {"node_id": node["node_id"], "rack_id": node["rack_id"], "passed": False,
                      "gpu_count": 0, "cpu_count": 0, "requests": 0}
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
            def get(path):
                if not isinstance(path, str) or not (path.startswith("/redfish/v1") or path in ["/readyz", "/livez"]):
                    raise ValueError("Unexpected BMC resource link")
                request = urllib.request.Request(node["bmc_url"].rstrip("/") + path,
                                                 headers={"Authorization": "Basic " + basic, "Accept": "application/json"})
                with opener.open(request, timeout=15) as response:
                    result["requests"] += 1
                    if response.status != 200:
                        raise ValueError("BMC HTTP status is not 200")
                    raw = response.read()
                    return raw.decode().strip() if path in ["/readyz", "/livez"] else json.loads(raw)
            try:
                target = urlsplit(node["bmc_url"])
                if target.scheme != "https" or target.hostname != self.settings["host_ip"] or target.port not in expected_ports:
                    raise ValueError("BMC node URL differs from bootstrap target")
                for path in ["/readyz", "/livez"]:
                    if get(path) != "ok":
                        raise ValueError("BMC readiness/liveness is not OK")
                service = get("/redfish/v1")
                collection = get(service["Systems"]["@odata.id"])
                path = "/redfish/v1/Systems/HGX_Baseboard_0"
                if path not in {item["@odata.id"] for item in collection["Members"]}:
                    raise ValueError("HGX system is absent")
                hgx = get(path)
                if hgx.get("Status", {}).get("Health") != "OK" or hgx.get("Status", {}).get("State") != "Enabled":
                    raise ValueError("HGX health/state is not ready")
                processors = get(hgx["Processors"]["@odata.id"])
                ids = set()
                for member in processors["Members"]:
                    processor = get(member["@odata.id"])
                    ids.add(processor["Id"])
                    if processor.get("Status", {}).get("Health") != "OK":
                        raise ValueError("Processor health is not OK")
                    metrics = get(processor["EnvironmentMetrics"]["@odata.id"])
                    reading = metrics.get("PowerWatts", {}).get("Reading")
                    limits = metrics.get("PowerLimitWatts", {})
                    if not finite(reading) or reading < 0 or not finite(limits.get("SetPoint")):
                        raise ValueError("Processor telemetry is not a finite numeric reading")
                    if processor.get("ProcessorType") == "GPU":
                        result["gpu_count"] += 1
                    elif processor.get("ProcessorType") == "CPU":
                        result["cpu_count"] += 1
                    else:
                        raise ValueError("Unknown processor type")
                if result["gpu_count"] != 4 or result["cpu_count"] != 2 or len(ids) != 6:
                    raise ValueError("HGX inventory is not four GPUs and two CPUs")
                result["passed"] = True
            except Exception as error:
                result["error"] = self.clean(error)[:600]
            return result
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.nodes = list(pool.map(verify, nodes))
        racks = {}
        for node in nodes:
            racks[node["rack_id"]] = racks.get(node["rack_id"], 0) + 1
        self.check("bmc-four-racks-72-health-inventory-telemetry",
                   len(self.nodes) == 72 and all(item["passed"] for item in self.nodes) and len(racks) == 4 and all(count == 18 for count in racks.values()),
                   {"passed_nodes": sum(item["passed"] for item in self.nodes), "rack_counts": racks,
                    "gpu_count": sum(item["gpu_count"] for item in self.nodes), "cpu_count": sum(item["cpu_count"] for item in self.nodes),
                    "get_requests": sum(item["requests"] for item in self.nodes), "ca_verification": "required", "methods": ["GET"],
                    "failed_nodes": [item for item in self.nodes if not item["passed"]]})

    def kubernetes(self):
        releases = json.loads(self.run([self.tools["helm"], "--kubeconfig", str(self.kubeconfig), "--kube-context",
                                       self.settings["kube_context"], "list", "-n", self.ns, "--all", "-o", "json"]).stdout)
        selected = [item for item in releases if item["name"] == self.release]
        self.check("helm-release-deployed-0.9.0", len(selected) == 1 and selected[0]["status"] == "deployed" and selected[0]["chart"] == "dps-0.9.0",
                   [{key: item.get(key) for key in ["name", "namespace", "revision", "status", "chart"]} for item in selected])
        items = self.kube("deployments,statefulsets")["items"]
        states = [{"name": item["metadata"]["name"], "replicas": item["spec"].get("replicas", 1),
                   "ready_replicas": item.get("status", {}).get("readyReplicas", 0)} for item in items]
        self.check("nine-dps-prs-s3-workloads-ready", len(states) == 9 and all(item["replicas"] > 0 and item["ready_replicas"] == item["replicas"] for item in states), states)
        self.pods = self.kube("pods")["items"]
        self.services = self.kube("services")["items"]
        self.check("no-bundled-postgresql-workload", not any("postgres" in item["name"] for item in states), {"external_pg": self.settings["pg_container"]})
        claims = [item for item in self.kube("pvc")["items"] if "seaweedfs" in item["metadata"]["name"]]
        self.check("three-s3-pvc-bound", len(claims) == 3 and all(item.get("status", {}).get("phase") == "Bound" for item in claims),
                   [{"name": item["metadata"]["name"], "phase": item.get("status", {}).get("phase")} for item in claims])
        expected = {"dps-postgresql", "dps-postgresql-ca", "bmc-shared-secret", "dps-bmc-ca", "dps-server-tls", "dps-agent-tls",
                    "dps-ingress-tls", "dps-jwt-keys", "dps-ldap-bind", "dps-ldap-ca", "dps-ldap-client-tls", "dps-prs-s3", "dps-prs-dps-auth"}
        output = self.run(self.kbase + ["get", "secrets", "-o", "custom-columns=NAME:.metadata.name", "--no-headers"]).stdout
        names = set(output.splitlines())
        self.check("thirteen-external-secrets-present", expected.issubset(names), {"expected": len(expected), "missing": sorted(expected - names)})

    def login(self):
        result, response = self.cli_result(["login", "--username", self.account["username"], "--password-stdin"],
                                           self.account["password"] + "\n")
        good = result.returncode == 0 and status_ok(response)
        self.check("cli-real-ldap-password-login", good, {"username": self.account["username"], "exit_code": result.returncode, "status_ok": status_ok(response)})
        if not good:
            raise RuntimeError("New LDAP user could not authenticate")
        self.credentials.chmod(0o600)
        saved = yaml.safe_load(self.credentials.read_text())
        token = saved["token"]["access_token"]
        self.private.append(token)
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * ((-len(encoded)) % 4)))
        roles = claims.get("roles", [])
        membership = claims.get("memberOf", [])
        if isinstance(membership, str):
            membership = [membership]
        self.check("cli-admin-role-from-ldap-group", "admin" in roles and any("dcpower-users" in group for group in membership),
                   {"roles": roles, "authorization_group_present": any("dcpower-users" in group for group in membership)})
        wrong = "wrong-" + secrets.token_urlsafe(28)
        self.private.append(wrong)
        bad_path = self.work / "wrong-password.yaml"
        result, response = self.cli_result(["login", "--username", self.account["username"], "--password-stdin"],
                                           wrong + "\n", credentials=bad_path, allow_failure=True)
        issued = False
        if bad_path.exists():
            bad = yaml.safe_load(bad_path.read_text()) or {}
            issued = bool(bad.get("token", {}).get("access_token"))
        diagnostic = self.clean(result.stdout + "\n" + result.stderr)
        auth_denial = bool(re.search(r"AUTHENTICATION_FAILED|UNAUTHENTICATED|invalid.credentials|authentication.failed|ldap.{0,40}(?:fail|invalid)", diagnostic, re.I))
        self.check("cli-wrong-password-rejected", result.returncode != 0 and not status_ok(response) and not issued and auth_denial,
                   {"exit_code": result.returncode, "status_ok": status_ok(response), "issued_token": issued, "authentication_rejection": auth_denial})

    def core(self):
        response = self.cli("server-version")
        found = bool(re.search(r"\bv?0\.9\.0\b", json.dumps(response)))
        self.check("dps-server-version-0.9.0", found)
        response = self.cli("verify", "--dps-server", "--database", "--auth")
        flags = {key: value.get("healthy") for key, value in response.items() if key != "status" and isinstance(value, dict)}
        self.check("core-database-auth-healthy", status_ok(response) and bool(flags) and all(value is True for value in flags.values()), flags)
        agents = self.cli("agent", "list")
        if isinstance(agents, dict):
            agents = agents.get("agents", [])
        self.check("agent-mtls-connected", any(item.get("agent_id") == self.settings["agent_id"] and item.get("connected") is True for item in agents),
                   [{"agent_id": item.get("agent_id"), "connected": item.get("connected")} for item in agents])
        topologies = self.cli("topology", "list").get("topologies", [])
        chosen = [item for item in topologies if len(item.get("leaf_node_names", [])) == 72]
        inactive = len(chosen) == 1 and not chosen[0].get("is_active", chosen[0].get("isActive", False))
        self.check("topology-72-leaves-inactive", len(topologies) == 1 and inactive,
                   [{"name": item.get("topology_name"), "leaf_nodes": len(item.get("leaf_node_names", [])),
                     "active": item.get("is_active", item.get("isActive", False))} for item in topologies])
        if len(chosen) == 1:
            self.raw_routing(chosen[0]["topology_name"])
        settings = self.cli("settings", "list")["settings"]
        self.check("persisted-prs-true-minus15-five-seconds",
                   str(settings.get("prs_enabled")).lower() == "true" and float(settings["prs_headroom_percent"]) == -15 and float(settings["prs_scheduler_interval_seconds"]) == 5,
                   {key: settings.get(key) for key in ["prs_enabled", "prs_headroom_percent", "prs_scheduler_interval_seconds"]})
        groups = self.cli("resource-group", "list").get("resource_groups", [])
        self.check("no-resource-groups-power-dispatch-not-started", groups == [], {"resource_group_count": len(groups), "core_agent_bmc_dispatch_tested": False})

    def raw_routing(self, topology_name):
        # Read the native streaming model; CLI export omits relation AgentId fields.
        saved = yaml.safe_load(self.credentials.read_text())
        token = saved["token"]["access_token"]
        service = self.service_for("server-http")
        port = next(item["port"] for item in service["spec"]["ports"] if item["name"] == "dps-http")
        url = "http://" + service["spec"]["clusterIP"] + ":" + str(port)
        url += "/nvidia.dcpower.v1.TopologyManagementService/GetTopologyModel"
        request = urllib.request.Request(url, data=json.dumps({"topology_name": topology_name}).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + token}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=25) as response:
            rows = [json.loads(line) for line in response.read().decode().splitlines() if line.strip()]
        relations = [entity for row in rows for entity in row.get("result", {}).get("entities", [])]
        desired = json.loads((self.cfg / "topology-4rack-dps09.json").read_text())
        computers = {entity["Name"] for entity in desired["Entities"] if entity["Type"] == "ComputerSystem"}
        mapping = {entity["entity"]["Name"]: entity["entity"].get("AgentId") for entity in relations}
        routed = sum(mapping.get(name) == self.settings["agent_id"] for name in computers)
        self.check("raw-topology-model-72-agent-route-metadata",
                   len(relations) == 110 and len(mapping) == 110 and len(computers) == 72 and routed == 72,
                   {"relation_count": len(relations), "unique_relations": len(mapping), "computer_count": len(computers),
                    "correct_agent_routes": routed, "expected_agent": self.settings["agent_id"],
                    "transport": "authenticated internal Core HTTP gateway", "topology_write_performed": False})

    def database(self):
        pg = self.settings["pg_container"]
        query = """SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM
(SELECT a.datname,a.usename,s.ssl,s.version FROM pg_stat_activity a
JOIN pg_stat_ssl s ON a.pid=s.pid WHERE a.usename='dps'
AND a.datname IN ('dps','dps_prs_config','dps_prs_config_staged','dps_prs_controller')) t;"""
        rows = json.loads(self.run(["docker", "exec", "-u", "postgres", pg, "psql", "-X", "-A", "-t", "-d", "postgres", "-c", query]).stdout)
        self.check("actual-app-postgresql-sessions-use-tls", bool(rows) and all(item["ssl"] for item in rows), {"sessions": rows})
        counts, owners = {}, {}
        for database in ["dps", "dps_prs_config", "dps_prs_config_staged", "dps_prs_controller"]:
            sql = "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';"
            counts[database] = int(self.run(["docker", "exec", "-u", "postgres", pg, "psql", "-X", "-A", "-t", "-d", database, "-c", sql]).stdout.strip())
            owner = "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database();"
            owners[database] = self.run(["docker", "exec", "-u", "postgres", pg, "psql", "-X", "-A", "-t", "-d", database, "-c", owner]).stdout.strip()
        self.check("core-and-three-prs-schema-migrations", all(count > 0 for count in counts.values()) and all(owner == "dps" for owner in owners.values()),
                   {"table_counts": counts, "owners": owners})
        self.check("configured-external-pg-verify-full",
                   self.values["postgresql"]["enabled"] is False and self.values["global"]["postgresql"]["sslMode"] == "verify-full")
        code = """import json,os,psycopg2
assert os.environ.get('PGSSLMODE')=='verify-full'
assert os.path.isfile(os.environ['PGSSLROOTCERT'])
names=[os.environ['DATABASE__NAME']]
if os.environ.get('DATABASE__STAGED_NAME'): names.append(os.environ['DATABASE__STAGED_NAME'])
rows=[]
for name in names:
 c=psycopg2.connect(host=os.environ['DATABASE__HOST'],port=os.environ['DATABASE__PORT'],
  user=os.environ['DATABASE__USER'],password=os.environ['DATABASE__PASSWORD'],dbname=name,connect_timeout=15)
 try:
  assert c.get_dsn_parameters()['sslmode']=='verify-full'
  with c.cursor() as q:
   q.execute('SELECT ssl,version FROM pg_stat_ssl WHERE pid=pg_backend_pid()')
   secure,version=q.fetchone();assert secure
   rows.append({'database':name,'ssl':secure,'tls_version':version,'sslmode':'verify-full'})
 finally:c.close()
print(json.dumps({'databases':rows,'all_verify_full':True}))
"""
        for role, count in [("config", 2), ("controller", 1)]:
            result = self.pod_code(self.pod_for("power-" + role), role, code)
            self.check("actual-" + role + "-pod-postgresql-verify-full",
                       result.get("all_verify_full") is True and len(result.get("databases", [])) == count, result)

    def prs(self):
        self.check("prs-both-switches-enabled", self.values["dps"]["prs"]["enabled"] is True and self.values["power-steering"]["enabled"] is True)
        roots = {}
        for role, port in [("config", 8000), ("controller", 8001)]:
            service = self.service_for("power-" + role)
            roots[role] = "http://" + service["spec"]["clusterIP"] + ":" + str(port)
            for health in ["startup", "live", "ready"]:
                status, _ = self.http(roots[role] + "/health/" + health)
                self.check(role + "-health-" + health, status == 200, {"http_status": status})
        status, body = self.http(roots["config"] + "/api/v1/domains?limit=10000")
        domains = json.loads(body)
        self.check("prs-domain-list-empty", status == 200 and domains.get("items") == [], {"domain_count": len(domains.get("items", []))})
        status, body = self.http(roots["controller"] + "/api/v1/scheduler")
        scheduler = json.loads(body)
        self.check("prs-scheduler-running-without-error", status == 200 and scheduler.get("status") in ["idle", "running"]
                   and scheduler.get("iteration_count", 0) > 0 and scheduler.get("last_error") is None,
                   {key: scheduler.get(key) for key in ["status", "iteration_count", "next_run_at", "last_run_at", "last_error"]})
        controller = self.pod_for("power-controller")
        code = """import json
from loguru import logger
logger.remove()
from controller.core.settings import settings
from controller.power_control.components.cluster.dps.dps import DpsCluster
s=settings.cluster.dps
assert not s.tls.insecure and not s.tls.skip_verify and s.tls.ca_cert_path and s.auth.enabled
cluster=DpsCluster(s)
r=cluster._api.topology.list_topologies()
assert r.get('status',{}).get('ok') is True
print(json.dumps({'strict_tls':True,'authenticated_protected_read':True,'topology_count':len(r.get('topologies',[]))}))
"""
        result = self.pod_code(controller, "controller", code)
        self.check("actual-controller-ldap-strict-tls-protected-dps-read",
                   result.get("strict_tls") is True and result.get("authenticated_protected_read") is True and result.get("topology_count") == 1, result)
        code = """import boto3,hashlib,json,os,secrets,urllib.request,urllib.error
from botocore.config import Config
endpoint=os.environ['AWS_ENDPOINT_URL']
client=boto3.client('s3',endpoint_url=endpoint,region_name='us-east-1',
 config=Config(signature_version='s3v4',s3={'addressing_style':'path'}))
bucket='dps-prs';client.head_bucket(Bucket=bucket)
key='verification/cold-bootstrap-'+secrets.token_hex(16);payload=secrets.token_bytes(64);written=False
try:
 client.put_object(Bucket=bucket,Key=key,Body=payload);written=True
 actual=client.get_object(Bucket=bucket,Key=key)['Body'].read()
 assert hashlib.sha256(actual).digest()==hashlib.sha256(payload).digest()
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 try:
  with opener.open(endpoint+'/'+bucket+'/'+key,timeout=15) as r:anonymous=r.status
 except urllib.error.HTTPError as e:anonymous=e.code
 assert anonymous in [401,403]
finally:
 if written:client.delete_object(Bucket=bucket,Key=key)
print(json.dumps({'signed_put_get_delete':True,'anonymous_http_status':anonymous,'temporary_object_deleted':True}))
"""
        result = self.pod_code(controller, "controller", code)
        self.check("s3-signed-put-get-delete", result.get("signed_put_get_delete") is True and result.get("temporary_object_deleted") is True, result)
        self.check("s3-anonymous-read-denied", result.get("anonymous_http_status") in [401, 403], {"http_status": result.get("anonymous_http_status")})

    def ui(self):
        base = "https://" + self.settings["ui_name"]
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                    urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(self.cfg / "tls/ca.crt"))),
                    urllib.request.HTTPCookieProcessor(jar))
        def request(path, body=None, token=None):
            headers = {"Origin": base, "X-Client-Id": "dps-ui-v2", "X-Client-Version": "0.9.0",
                       "Content-Type": "application/json", "X-DPS-Session": "1"}
            if token:
                headers["Authorization"] = "Bearer " + token
            req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers=headers, method="POST")
            try:
                with opener.open(req, timeout=25) as response:
                    status, raw = response.status, response.read()
            except urllib.error.HTTPError as error:
                status, raw = error.code, error.read()
            return status, json.loads(raw) if raw else {}
        token = None
        try:
            status, response = request("/api/session/login", {"username": self.account["username"], "password": self.account["password"]})
            token = response.get("accessToken")
            if token:
                self.private.append(token)
            self.check("ui-real-ldap-session-login-strict-ca", status == 200 and bool(token) and len(jar) > 0,
                       {"http_status": status, "session_cookie_present": len(jar) > 0})
            if not token:
                raise RuntimeError("UI did not issue a test session")
            status, response = request("/api/nvidia.dcpower.v1.TopologyManagementService/ListTopologies", {}, token)
            self.check("ui-authorized-topology-read", status == 200 and status_ok(response) and len(response.get("topologies", [])) == 1,
                       {"http_status": status, "topology_count": len(response.get("topologies", []))})
        finally:
            if token:
                status, _ = request("/api/session/logout", token=token)
                self.check("ui-test-session-logout", status == 204, {"http_status": status})
            jar.clear()
        wrong = "wrong-" + secrets.token_urlsafe(28)
        self.private.append(wrong)
        status, response = request("/api/session/login", {"username": self.account["username"], "password": wrong})
        self.check("ui-wrong-password-rejected", status in [400, 401] and not response.get("accessToken"),
                   {"http_status": status, "issued_token": bool(response.get("accessToken"))})

    def execute(self):
        output = self.root / "verification/reports/cold-bootstrap-fullstack.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        private_directory = self.root / "verification/private"
        private_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_directory.chmod(0o700)
        default = self.cfg / "dpsctl/credentials.yaml"
        before = default.read_bytes() if default.exists() else None
        with tempfile.TemporaryDirectory(prefix=".fullstack-session-", dir=private_directory) as directory:
            self.work = Path(directory)
            self.credentials = self.work / "valid-credentials.yaml"
            for name, method in [
                ("docker-services", self.docker), ("72-bmc-endpoints", self.bmc), ("kubernetes-release", self.kubernetes),
                ("cli-ldap-login", self.login), ("core-topology-effective-prs", self.core),
                ("postgresql-migrations-and-pod-tls", self.database), ("prs-controller-storage", self.prs), ("ui-ldap-session", self.ui),
            ]:
                self.attempt(name, method)
            after = default.read_bytes() if default.exists() else None
            self.check("existing-default-cli-credentials-unchanged", before == after, {"default_file_existed": before is not None})
            logs = self.work / "dpsctl.log"
            if logs.exists():
                safe_log = self.root / "verification/logs/cold-bootstrap-fullstack-dpsctl.log"
                safe_log.parent.mkdir(parents=True, exist_ok=True)
                safe_log.write_text(self.clean(logs.read_text(errors="replace")))
                safe_log.chmod(0o600)
        report = {
            "checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "root": str(self.root),
            "namespace": self.ns, "release": self.release, "settings_file": str(self.cfg / "bootstrap-settings.json"),
            "checks": self.checks, "bmc_node_results": self.nodes,
            "summary": {"total": len(self.checks), "passed": sum(item["passed"] for item in self.checks),
                        "failed": sum(not item["passed"] for item in self.checks), "all_passed": all(item["passed"] for item in self.checks)},
            "hardware_write_operations": 0, "topology_activation_performed": False, "deployment_performed": False,
            "cli_test_credentials_removed": True, "s3_writes": "Only a randomly named test object; delete in finally",
            "limits": ["Topology remains inactive; Core-to-Agent BMC dispatch and a power-control loop are not claimed as passed.",
                       "BMC checks are CA-verified GETs from the host and verify 4 racks/72 endpoints/288 GPUs/144 CPUs.",
                       "Simulator authentication is not enforced and fixture model text may still be GB200/Generic.",
                       "This verifier does not install/rebuild/restore/clean up services, namespaces, volumes or Git."],
        }
        output.write_text(json.dumps(self.safe(report), indent=2) + "\n")
        output.chmod(0o600)
        print(json.dumps({"report": str(output), **report["summary"]}))
        return 0 if report["summary"]["all_passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        return Verification(args.root).execute()
    except Exception as error:
        # Initialization errors do not include private input values.
        text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED_JWT]", str(error))
        print(json.dumps({"status": "error", "error": text[:1000]}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
