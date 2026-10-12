#!/usr/bin/env python3
"""Verify fixed PRS image identities and import them into native K3s."""
IMAGE_NAMES = {'power-config', 'opentelemetry-collector-contrib', 'busybox', 'power-controller', 'seaweedfs'}
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

import hashlib
from bootstrap_common import private
package = ctx.runtime_path("dps-install/packages/prs")
manifest = ctx.runtime_path("dps-install/config/prs/runtime-images.json")
archive = package / "prs-2.1.0-runtime.tar"
for path in (manifest, archive):
    if path.is_symlink():
        raise RuntimeError("PRS runtime input is a symlink; preserve and review")
old = json.loads(manifest.read_text()) if manifest.exists() else None
rows = [{"tag": row["tag"], "digest": row["image_digest"], "image_id": row["image_id"]} for row in records]
if old:
    previous = {row["tag"]: row for row in old["images"]}
    if set(previous) != set(tags):
        raise RuntimeError("Recorded PRS image set changed; preserve and review")
    for row in rows:
        earlier = previous[row["tag"]]
        if earlier["image_id"] != row["image_id"] or earlier["digest"].rsplit("@", 1)[-1] != row["digest"].rsplit("@", 1)[-1]:
            raise RuntimeError("Recorded PRS image identity changed: " + row["tag"])
package.mkdir(parents=True, exist_ok=True)
if archive.exists() and not old:
    raise RuntimeError("Unrecorded PRS archive exists; preserve and review")
if not archive.exists():
    with tempfile.NamedTemporaryFile(dir=package, suffix=".tar", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        subprocess.run(["docker", "save", "--output", str(temporary), *tags], check=True)
        temporary.chmod(0o600)
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
digest = hashlib.sha256()
with archive.open("rb") as stream:
    for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
        digest.update(block)
checksum = digest.hexdigest()
if old and old["archive_sha256"] != checksum:
    raise RuntimeError("Recorded PRS archive checksum changed; preserve and review")
private(manifest, {"images": rows, "archive": str(archive), "archive_sha256": checksum})
subprocess.run(["k3s", "ctr", "-n", "k8s.io", "images", "import", str(archive)], check=True, stdout=subprocess.DEVNULL)
print(json.dumps({"imported_images": len(records), "archive": str(archive), "archive_sha256": checksum}))
