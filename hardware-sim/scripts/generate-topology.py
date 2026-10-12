#!/usr/bin/env python3
"""Derive a DPS 0.9 four-rack GB300 simulation topology without contacting DPS."""

import sys
sys.dont_write_bytecode = True
from pathlib import Path as _DeploymentPath
sys.path.insert(0, str(_DeploymentPath(__file__).resolve().parents[2] / 'dps-install/scripts'))
from deployment_context import context_from_cli
CTX = context_from_cli()
SETTINGS = CTX.settings
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=CTX.source_path("dps-install/templates/topology-4rack-dps09.json"))
    parser.add_argument("--output-dir", type=Path, default=CTX.runtime_path("hardware-sim/runtime"))
    parser.add_argument("--dps-config-dir", type=Path, default=CTX.runtime_path("dps-install/config"))
    parser.add_argument("--report-dir", type=Path, default=CTX.runtime_path("verification/reports"))
    parser.add_argument("--bmc-host", default=SETTINGS["host_ip"])
    parser.add_argument("--start-port", type=int, default=SETTINGS["bmc_start_port"])
    parser.add_argument("--secret-name", default="bmc-shared-secret")
    parser.add_argument("--topology-name", default=SETTINGS["topology_name"])
    parser.add_argument("--agent-id", default=SETTINGS["agent_id"])
    args = parser.parse_args()
    require(bool(args.agent_id.strip()), "Agent ID must be non-empty")
    for output in (args.output_dir, args.dps_config_dir, args.report_dir):
        require(output.resolve().is_relative_to(CTX.runtime_root),
                "All generated files must remain under the selected runtime directory")
    source_bytes = args.source.read_bytes()
    source = json.loads(source_bytes)
    require(set(source) in ({"Entities", "Topology"}, {"Entities", "Topology", "Policies"}), "Unexpected source top-level schema")
    require(isinstance(source["Entities"], list), "Entities must be an array")
    require(isinstance(source["Topology"], dict) and isinstance(source["Topology"]["Entities"], list),
            "Topology.Entities must be an array")
    entity_names = [e["Name"] for e in source["Entities"]]
    require(len(entity_names) == len(set(entity_names)), "Source has duplicate entity names")
    by_name = {e["Name"]: e for e in source["Entities"]}
    names_by_rack = {
        f"gb300-rack-{rack:02d}": [f"gb300-r{rack:02d}-{index:04d}" for index in range(1, 19)]
        for rack in range(1, 5)
    }
    ordered_nodes = [name for rack_nodes in names_by_rack.values() for name in rack_nodes]
    ordered_psus = [f"PSU-R{rack:02d}-{index}" for rack in range(1, 5) for index in range(1, 9)]
    infrastructure = [e["Name"] for e in source["Entities"]
                      if e["Type"] in ("PowerDomain", "PowerDistribution")]
    require(Counter(by_name[n]["Type"] for n in infrastructure) ==
            Counter({"PowerDomain": 2, "PowerDistribution": 4}), "Expected two domains and four PDUs")
    retained = set(ordered_nodes + ordered_psus + infrastructure)
    require(retained.issubset(by_name), "Source is missing required four-rack entities")
    require(len(retained) == 110, "Expected 110 retained entities")
    result = deepcopy(source)
    legacy_policies = result.pop("Policies", [])
    result["Entities"] = [e for e in result["Entities"] if e["Name"] in retained]
    for entity in result["Entities"]:
        entity.pop("AgentId", None)
    nodes = []
    require(1 <= args.start_port <= 65535 - len(ordered_nodes) + 1, "Invalid port range")
    for index, name in enumerate(ordered_nodes):
        entity = next(e for e in result["Entities"] if e["Name"] == name)
        require(entity["Type"] == "ComputerSystem" and entity["Model"] == "DGX_GB300",
                f"{name} is not an upstream DGX_GB300 computer system")
        rack = index // 18 + 1
        port = args.start_port + index
        bmc_url = f"https://{args.bmc_host}:{port}"
        entity["Redfish"] = {"URL": bmc_url, "SecretName": args.secret_name}
        nodes.append({
            "rack_id": f"gb300-rack-{rack:02d}",
            "node_id": name,
            "node_index": index % 18 + 1,
            "model": entity["Model"],
            "port": port,
            "bmc_url": bmc_url,
            "secret_name": args.secret_name,
        })
    result["Topology"]["Name"] = args.topology_name
    topology_entries = []
    for entry in result["Topology"]["Entities"]:
        if entry["Name"] not in retained:
            continue
        if "Children" in entry:
            entry["Children"] = [name for name in entry["Children"] if name in retained]
        entry.pop("AgentId", None)
        if entry["Name"] in ordered_nodes:
            entry["AgentId"] = args.agent_id
        topology_entries.append(entry)
    result["Topology"]["Entities"] = topology_entries

    # Validate structural invariants without calling any DPS service.
    names = [e["Name"] for e in result["Entities"]]
    topo_names = [e["Name"] for e in topology_entries]
    require(len(names) == len(set(names)), "Duplicate generated entity IDs")
    require(len(topo_names) == len(set(topo_names)), "Duplicate topology IDs")
    require(set(names) == set(topo_names), "Topology and entity IDs differ")
    generated_by_name = {e["Name"]: e for e in result["Entities"]}
    entity_type_counts = Counter(e["Type"] for e in result["Entities"])
    require(entity_type_counts == Counter({
        "ComputerSystem": 72, "PowerSupply": 32, "PowerDistribution": 4, "PowerDomain": 2
    }), "Incorrect generated entity counts")
    graph = {e["Name"]: e.get("Children", []) for e in topology_entries}
    dangling = [{"parent": parent, "child": child} for parent, children in graph.items()
                for child in children if child not in generated_by_name]
    require(not dangling, f"Dangling child references: {dangling}")
    require(all(len(children) == len(set(children)) for children in graph.values()),
            "Duplicate children in generated topology")
    all_children = {child for children in graph.values() for child in children}
    roots = sorted(set(graph) - all_children)
    require(roots == ["Utility"], f"Unexpected graph roots: {roots}")
    state = {}
    def visit(name):
        require(state.get(name) != 1, f"Cycle detected at {name}")
        if state.get(name) == 2:
            return
        state[name] = 1
        for child in graph[name]:
            visit(child)
        state[name] = 2
    for root in roots:
        visit(root)
    require(set(state) == retained, "Disconnected retained entities")
    leaf_names = {name for name, children in graph.items() if not children}
    require(leaf_names == set(ordered_nodes), "Expected only ComputerSystems as leaves")
    for rack in range(1, 5):
        expected_nodes = set(names_by_rack[f"gb300-rack-{rack:02d}"])
        expected_psus = {f"PSU-R{rack:02d}-{index}" for index in range(1, 9)}
        require(set(graph[f"FloorPDU-{rack}"]) == expected_psus, "PDU rack mapping incorrect")
        for psu in expected_psus:
            require(set(graph[psu]) == expected_nodes, "PSU node mapping incorrect")
    node_urls = [n["bmc_url"] for n in nodes]
    require(len(node_urls) == len(set(node_urls)) == 72, "Duplicate BMC URLs")
    require("Policies" not in result, "DPS 0.9 installation input must not contain legacy policies")
    routed = {e["Name"] for e in topology_entries if e.get("AgentId") == args.agent_id}
    require(routed == set(ordered_nodes), "All 72 compute relationships must have the configured AgentId")
    require(not any("AgentId" in e for e in result["Entities"]), "AgentId belongs on topology relationships")

    # Ensure no deleted node name survives in any object or scalar reference.
    removed = set(entity_names) - retained
    forbidden = []
    def find_removed(value, path):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in removed:
                    forbidden.append(path + "." + key)
                find_removed(child, path + "." + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                find_removed(child, f"{path}[{index}]")
        elif isinstance(value, str) and value in removed:
            forbidden.append(path)
    find_removed(result, "$")
    require(not forbidden, f"Deleted entity references remain: {forbidden}")
    require(args.source.read_bytes() == source_bytes, "Upstream topology changed during generation")
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    args.dps_config_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    topology_path = args.dps_config_dir / "topology-4rack-dps09.json"
    nodes_path = output_dir / "nodes.json"
    check_path = args.report_dir / "topology-check.json"
    save_json(topology_path, result)
    save_json(nodes_path, nodes)
    check = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "source_path": str(args.source),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_preserved": True,
        "topology_path": str(topology_path),
        "topology_name": result["Topology"]["Name"],
        "racks": {
            rack_id: {"computers": len(rack_nodes), "power_supplies": 8,
                      "pdu": f"FloorPDU-{index}"}
            for index, (rack_id, rack_nodes) in enumerate(names_by_rack.items(), 1)
        },
        "rack_count": 4,
        "entity_count": len(result["Entities"]),
        "topology_entity_count": len(topology_entries),
        "entity_type_counts": dict(entity_type_counts),
        "computer_model": "DGX_GB300",
        "unique_ids": True,
        "unique_bmc_urls": True,
        "bmc_count": len(nodes),
        "bmc_host": args.bmc_host,
        "bmc_port_range": [args.start_port, args.start_port + len(nodes) - 1],
        "bmc_reachability_checked": False,
        "secret_name": args.secret_name,
        "credentials_included": False,
        "dangling_references": dangling,
        "deleted_entity_reference_paths": forbidden,
        "acyclic": True,
        "fully_connected": True,
        "roots": roots,
        "edge_count": sum(map(len, graph.values())),
        "leaf_count": len(leaf_names),
        "legacy_policies_removed": [p["Name"] for p in legacy_policies],
        "policies_in_installation_input": False,
        "agent_id": args.agent_id,
        "agent_assignment_location": "Topology.Entities",
        "agent_assigned_compute_nodes": len(routed),
        "validation_scope": "Offline JSON shape and graph checks; derived from the public GB300 topology blueprint.",
        "dps_server_schema_validation": "Offline generator does not contact DPS; server validation is a separate install step.",
        "schema_caveats": [
            "Physical racks are represented by stable node/PSU identifiers and floor-PDU grouping, not separate Rack entities.",
            "Redfish endpoint reachability and authentication must be validated after the simulator and router are started.",
            "The shared bmc-shared-secret must exist before DPS accesses the BMCs; no Kubernetes Secret is created here.",
            "Simulator GB300 metrics and control behavior are synthetic; no physical GB300 rack behavior is implied."
        ],
    }
    save_json(check_path, check)
    print(json.dumps({
        "status": "pass", "rack_count": 4, "computer_systems": 72,
        "power_supplies": 32, "pdus": 4, "power_domains": 2,
        "edge_count": check["edge_count"],
        "files": [str(topology_path), str(nodes_path), str(check_path)]
    }))


if __name__ == "__main__":
    main()

