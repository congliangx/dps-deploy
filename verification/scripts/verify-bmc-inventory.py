#!/usr/bin/env python3
"""Read-only, eight-worker inventory verification of all simulated GB300 BMCs."""
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import os
import sys
from pathlib import Path
import ssl
import urllib.error
import urllib.request

os.umask(0o077)
BASE = Path("/raid/vince/deploy")
nodes = json.loads((BASE / "hardware-sim/runtime/nodes.json").read_text())
topology = json.loads((BASE / "dps-install/config/topology-4rack-dps09.json").read_text())
credentials = json.loads((BASE / "dps-install/config/bmc-credentials.json").read_text())
token = base64.b64encode(f'{credentials["username"]}:{credentials["password"]}'.encode()).decode()
context = ssl.create_default_context(cafile=str(BASE / "dps-install/config/simulator-ca.crt"))
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
expected_ids = {f"GPU_{i}" for i in range(4)} | {f"CPU_{i}" for i in range(2)}

def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

def verify_node(node):
    result = {"rack_id": node["rack_id"], "node_id": node["node_id"],
              "bmc_url": node["bmc_url"], "topology_model": node["model"],
              "http_checks": [], "processors": [], "errors": [], "deviations": []}
    def require(condition, message):
        if not condition:
            result["errors"].append(message)
    def get(path):
        if not isinstance(path, str) or not (path.startswith("/redfish/v1") or path in ["/readyz", "/livez"]):
            raise ValueError(f"Invalid Redfish resource link {path!r}")
        request = urllib.request.Request(node["bmc_url"] + path, headers={
            "Authorization": "Basic " + token, "Accept": "application/json"})
        with opener.open(request, timeout=20) as response:
            raw = response.read()
            payload = {"response": raw.decode().strip()} if path in ["/readyz", "/livez"] else json.loads(raw)
            result["http_checks"].append({"path": path, "status": response.status})
            require(response.status == 200, f"Non-200 response for {path}")
            return payload
    def check_power(payload, resource, expected_maximum):
        power = payload.get("PowerWatts", {}).get("Reading")
        limit = payload.get("PowerLimitWatts", {})
        values = {key: limit.get(key) for key in ("AllowableMin", "AllowableMax", "SetPoint", "Reading")}
        require(finite_number(power) and power >= 0, f"{resource}: invalid power reading")
        require(all(finite_number(v) for v in values.values()), f"{resource}: invalid power limits")
        if all(finite_number(v) for v in values.values()):
            require(values["AllowableMin"] <= values["AllowableMax"], f"{resource}: reversed allowable limits")
            require(values["AllowableMin"] <= values["SetPoint"] <= values["AllowableMax"],
                    f"{resource}: set point outside allowable range")
            require(values["AllowableMin"] <= values["Reading"] <= values["AllowableMax"],
                    f"{resource}: limit reading outside allowable range")
            if expected_maximum is not None:
                require(values["AllowableMax"] == expected_maximum,
                        f"{resource}: unexpected maximum power limit {values['AllowableMax']}")
        return {"power_watts": power, "power_limit_watts": values,
                "control_mode": limit.get("ControlMode"), "environment_metrics_path": resource}

    try:
        result["service_health"] = {}
        for path in ["/readyz", "/livez"]:
            health = get(path)
            result["service_health"][path] = health.get("response")
            require(health.get("response") == "ok", f"{path}: health probe not OK")
        root = get("/redfish/v1")
        result["service_root"] = {key: root.get(key) for key in (
            "Id", "Product", "Vendor", "RedfishVersion", "UUID")}
        require(root.get("@odata.type", "").startswith("#ServiceRoot."), "Incorrect service-root type")
        system_collection = get(root["Systems"]["@odata.id"])
        system_paths = [member["@odata.id"] for member in system_collection["Members"]]
        result["discovered_system_paths"] = system_paths
        hgx_path = "/redfish/v1/Systems/HGX_Baseboard_0"
        require(hgx_path in system_paths, "HGX_Baseboard_0 system was not discovered")
        systems = [get(path) for path in system_paths]
        result["systems"] = [{key: system.get(key) for key in (
            "@odata.id", "Id", "Model", "Name", "Manufacturer", "SerialNumber", "UUID", "PowerState", "Status")}
            for system in systems]
        for system in systems:
            status = system.get("Status", {})
            require(status.get("Health") == "OK", f'{system["Id"]}: system health is not OK')
            require(status.get("State") == "Enabled", f'{system["Id"]}: system state is not Enabled')
            require(status.get("HealthRollup", "OK") == "OK", f'{system["Id"]}: rollup health is not OK')
            require(system.get("PowerState") == "On", f'{system["Id"]}: power state is not On')
        managers = get(root["Managers"]["@odata.id"])
        result["managers"] = []
        for member in managers["Members"]:
            manager = get(member["@odata.id"])
            status = manager.get("Status", {})
            result["managers"].append({key: manager.get(key) for key in ["Id", "ManagerType", "Status"]})
            require(status.get("Health") == "OK", f'{manager["Id"]}: BMC health is not OK')
            require(status.get("State") == "Enabled", f'{manager["Id"]}: BMC state is not Enabled')
            require(status.get("HealthRollup", "OK") == "OK", f'{manager["Id"]}: BMC rollup health is not OK')
        hgx = next(system for system in systems if system["Id"] == "HGX_Baseboard_0")
        require(hgx.get("Status", {}).get("Health") == "OK", "HGX system health is not OK")
        if root.get("Product") == "GB200 NVL":
            result["deviations"].append("Upstream service-root Product remains GB200 NVL in the GB300 simulator.")
        if any(system.get("Model") == "GB200 NVL" for system in systems):
            result["deviations"].append("Upstream ComputerSystem.Model remains GB200 NVL in the GB300 simulator.")
        processor_collection = get(hgx["Processors"]["@odata.id"])
        processor_paths = [member["@odata.id"] for member in processor_collection["Members"]]
        require({path.rsplit("/", 1)[-1] for path in processor_paths} == expected_ids,
                "HGX processor inventory differs from two CPUs and four GPUs")
        require(processor_collection.get("Members@odata.count") == 6, "Incorrect processor collection count")
        for path in processor_paths:
            processor = get(path)
            processor_id = processor["Id"]
            processor_type = processor.get("ProcessorType")
            require(processor_id in expected_ids, f"Unexpected processor {processor_id}")
            require(processor_type == ("GPU" if processor_id.startswith("GPU") else "CPU"),
                    f"{processor_id}: incorrect processor type")
            require(processor.get("Status", {}).get("Health") == "OK", f"{processor_id}: health is not OK")
            require(processor.get("Status", {}).get("State") == "Enabled", f"{processor_id}: state is not Enabled")
            environment_path = processor["EnvironmentMetrics"]["@odata.id"]
            environment = get(environment_path)
            metrics_path = processor["Metrics"]["@odata.id"]
            metrics = get(metrics_path)
            require(metrics.get("@odata.type", "").startswith("#ProcessorMetrics."),
                    f"{processor_id}: incorrect processor metrics type")
            inventory = {key: processor.get(key) for key in (
                "@odata.id", "Id", "Model", "Manufacturer", "ProcessorType", "SerialNumber",
                "UUID", "TotalCores", "TotalThreads", "MemorySummary", "Status")}
            inventory["processor_metrics_path"] = metrics_path
            inventory["environment"] = check_power(environment, environment_path,
                                                   1400 if processor_type == "GPU" else None)
            result["processors"].append(inventory)
        gpu_models = sorted({processor["Model"] for processor in result["processors"]
                             if processor["ProcessorType"] == "GPU"})
        if gpu_models == ["Generic"]:
            result["deviations"].append("Upstream GPU Processor.Model is Generic.")
        chassis_links = hgx["Links"]["Chassis"]
        chassis_path = next(link["@odata.id"] for link in chassis_links
                            if link["@odata.id"].endswith("HGX_Chassis_0"))
        chassis = get(chassis_path)
        environment_path = chassis.get("EnvironmentMetrics", {}).get(
            "@odata.id", chassis_path + "/EnvironmentMetrics")
        environment = get(environment_path)
        result["chassis"] = {key: chassis.get(key) for key in (
            "@odata.id", "Id", "Model", "Manufacturer", "SerialNumber", "UUID", "Status", "PowerState")}
        require(chassis.get("Status", {}).get("Health") == "OK", "HGX chassis health is not OK")
        require(chassis.get("Status", {}).get("State") == "Enabled", "HGX chassis state is not Enabled")
        require(chassis.get("Status", {}).get("HealthRollup", "OK") == "OK", "HGX chassis rollup health is not OK")
        require(chassis.get("PowerState") == "On", "HGX chassis power is not On")
        if chassis.get("Model") == "GB200 NVL":
            result["deviations"].append("Upstream Chassis.Model remains GB200 NVL in the GB300 simulator.")
        result["chassis"]["environment"] = check_power(environment, environment_path, 5600)
        control_path = environment.get("PowerLimitWatts", {}).get("DataSourceUri")
        if control_path:
            control = get(control_path)
            result["chassis"]["total_gpu_control"] = {
                key: control.get(key) for key in ("@odata.id", "Id", "ControlType", "SetPoint",
                                                "Reading", "AllowableMin", "AllowableMax")}
        result["gpu_count"] = sum(p["ProcessorType"] == "GPU" for p in result["processors"])
        result["cpu_count"] = sum(p["ProcessorType"] == "CPU" for p in result["processors"])
        require(result["gpu_count"] == 4 and result["cpu_count"] == 2, "Incorrect final processor counts")
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    result["status"] = "pass" if not result["errors"] else "fail"
    return result

with ThreadPoolExecutor(max_workers=8) as executor:
    results = list(executor.map(verify_node, nodes))
topology_nodes = {entity["Name"] for entity in topology["Entities"] if entity["Type"] == "ComputerSystem"}
map_nodes = {node["node_id"] for node in nodes}
failures = [result for result in results if result["status"] != "pass"]
deviation_counts = Counter(deviation for result in results for deviation in result["deviations"])
report = {
    "verified_at_utc": datetime.now(timezone.utc).isoformat(),
    "verification_scope": "Read-only HTTPS GET from L20-12 using actual public BMC URLs and eight concurrent workers.",
    "source_nodes_path": str(BASE / "hardware-sim/runtime/nodes.json"),
    "source_topology_path": str(BASE / "dps-install/config/topology-4rack-dps09.json"),
    "credentials_path": str(BASE / "dps-install/config/bmc-credentials.json"),
    "authentication": "Supplied credentials were sent; endpoint access restriction is evaluated separately.",
    "verification_script": str(BASE / "verification/scripts/verify-bmc-inventory.py"),
    "tls_certificate_verification": "strict CA and endpoint identity verification using config/simulator-ca.crt",
    "tls_ca_verified": True,
    "passed": not failures,
    "mutating_requests_sent": False,
    "maximum_workers": 8,
    "status": "pass_with_upstream_fixture_deviations" if not failures else "fail",
    "node_count": len(results),
    "passed_nodes": len(results) - len(failures),
    "failed_nodes": len(failures),
    "rack_count": len({node["rack_id"] for node in nodes}),
    "rack_counts": dict(Counter(node["rack_id"] for node in nodes)),
    "gpu_count": sum(result.get("gpu_count", 0) for result in results),
    "cpu_count": sum(result.get("cpu_count", 0) for result in results),
    "request_count": sum(len(result["http_checks"]) for result in results),
    "cpu_allowable_maximum_watts": sorted({processor["environment"]["power_limit_watts"]["AllowableMax"]
        for result in results for processor in result["processors"] if processor["ProcessorType"] == "CPU"}),
    "node_map_matches_topology": map_nodes == topology_nodes,
    "deviation_counts": dict(deviation_counts),
    "limitations": [
        "SDK GB300 power capabilities and 4-GPU/2-CPU inventory are present, but some upstream captured fixture identity strings still identify GB200 or Generic.",
        "This report verifies simulator inventory and reads only; it does not claim DPS integration or physical GB300 hardware validation.",
        "Repeated serial numbers and UUID values come from shared upstream response fixtures and do not identify distinct physical devices."
    ],
    "nodes": results,
}
(BASE / "verification/reports/verification-inventory.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({key: report[key] for key in (
    "status", "rack_count", "node_count", "passed_nodes", "failed_nodes", "gpu_count",
    "cpu_count", "request_count", "node_map_matches_topology", "deviation_counts")}))
if failures:
    print(json.dumps({"failed_node_ids": [result["node_id"] for result in failures]}))
    sys.exit(1)

