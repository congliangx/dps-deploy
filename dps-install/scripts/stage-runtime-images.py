#!/usr/bin/env python3
"""Stage pinned DPS images into native K3s without deploying workloads."""
IMAGE_NAMES = {'dps-ui', 'dps-core-agent', 'postgresql-server-and-migration-client'}
import sys
sys.dont_write_bytecode = True
import argparse
parser = argparse.ArgumentParser(description=__doc__, epilog="Shared deployment options: --config FILE, --runtime-root DIR and deployment overrides.")
if any(arg in ("--help", "-h") for arg in sys.argv[1:]):
    parser.print_help()
    raise SystemExit(0)
from deployment_context import context_from_cli
ctx = context_from_cli()
parser.parse_args()
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path
os.umask(0o077)
sources = json.loads(ctx.source_path("dps-install/config/artifact-sources.json").read_text())
selected = [item for item in sources["images"] if item["name"] in IMAGE_NAMES]
if len(selected) != len(IMAGE_NAMES):
    raise RuntimeError("Required image pins are missing from artifact-sources.json")
loader = importlib.util.spec_from_file_location("dps_artifact_download", ctx.source_path("dps-install/scripts/download-artifacts.py"))
acquisition = importlib.util.module_from_spec(loader)
loader.loader.exec_module(acquisition)
acquisition.ctx = ctx
subprocess.run(["systemctl", "is-active", "--quiet", "k3s"], check=True)
records = acquisition.image_set(selected)
tags = [row["tag"] for row in records]

package = ctx.runtime_path("dps-install/packages/images")
package.mkdir(parents=True, exist_ok=True)
archive = package / "dps-0.9.0-runtime.tar"
if archive.is_symlink():
    raise RuntimeError("Image archive is a symlink; preserve and review")
with tempfile.NamedTemporaryFile(dir=package, suffix=".tar", delete=False) as stream:
    temporary = Path(stream.name)
try:
    subprocess.run(["docker", "save", "--output", str(temporary), *tags], check=True)
    temporary.chmod(0o600)
    temporary.replace(archive)
    subprocess.run(["k3s", "ctr", "--namespace", "k8s.io", "images", "import", str(archive)], check=True)
finally:
    temporary.unlink(missing_ok=True)
print("Pinned DPS images imported into native containerd; no workloads deployed.")
