#!/usr/bin/env python3
"""Acquire pinned DPS 0.9 artifacts and build the independent cold LDAP image.

This entry point downloads/caches artifacts only. It does not start containers,
modify Kubernetes, initialize identities, or tag the running LDAP image.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from deployment_context import context_from_cli
ctx = context_from_cli()
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request


class ArtifactError(RuntimeError):
    pass


def digest_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def regular(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ArtifactError(f"Refuse non-regular cache path: {path}")


def relative(root, value):
    p = Path(value)
    if p.is_absolute() or ".." in p.parts:
        raise ArtifactError(f"Invalid relative artifact path: {value}")
    target = root / p
    parent = target.parent.resolve()
    if not parent.is_relative_to(root) or not target.resolve().is_relative_to(root):
        raise ArtifactError(f"Artifact path leaves root: {value}")
    return target


class HTTPSOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ArtifactError("Refuse non-HTTPS artifact redirect")
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if (urllib.parse.urlsplit(req.full_url).netloc !=
                urllib.parse.urlsplit(newurl).netloc):
            result.remove_header("Authorization")
        return result


OPENER = urllib.request.build_opener(
    HTTPSOnlyRedirect(),
    urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def request(url):
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ArtifactError("Artifact URL must use HTTPS")
    headers = {"User-Agent": "dps-deploy-artifacts/0.9"}
    key = os.environ.get("NGC_API_KEY")
    if key and urllib.parse.urlsplit(url).netloc == "helm.ngc.nvidia.com":
        token = base64.b64encode(("$oauthtoken:" + key).encode()).decode()
        headers["Authorization"] = "Basic " + token
    return OPENER.open(urllib.request.Request(url, headers=headers), timeout=60)


def publish_new(temp, target, expected):
    try:
        os.link(temp, target)
        target.chmod(0o644)
    except FileExistsError:
        regular(target)
        if digest_file(target) != expected:
            raise ArtifactError(f"Concurrent conflicting cache, preserved: {target}")
    finally:
        temp.unlink(missing_ok=True)


def fetch(url, target, expected):
    regular(target)
    if target.exists():
        if digest_file(target) != expected:
            raise ArtifactError(f"Conflicting cache, preserved: {target}")
        emit("cache-verified", path=str(target))
        return {"path": str(target), "sha256": expected, "cached": True}
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
                tmp = Path(out.name)
                h = hashlib.sha256()
                size = 0
                with request(url) as response:
                    for block in iter(lambda: response.read(1024 * 1024), b""):
                        out.write(block)
                        h.update(block)
                        size += len(block)
            if h.hexdigest() != expected:
                raise ArtifactError(f"Downloaded SHA256 mismatch: {target.name}")
            publish_new(tmp, target, expected)
            emit("download-verified", path=str(target), bytes=size)
            return {"path": str(target), "sha256": expected, "cached": False}
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise ArtifactError(
                    f"HTTP {exc.code} from {urllib.parse.urlsplit(url).netloc}; "
                    "use an authorized NGC_API_KEY or registry login; TLS remains enabled")
            if attempt == 2:
                raise ArtifactError(
                    f"HTTP {exc.code} from {urllib.parse.urlsplit(url).netloc}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == 2:
                raise ArtifactError(
                    f"Download failed for {target.name}: {type(exc).__name__}")
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        time.sleep(attempt + 1)
    raise ArtifactError(f"Unable to download {target.name}")


def copy_verified(source, target, expected):
    regular(source)
    if not source.is_file() or digest_file(source) != expected:
        raise ArtifactError("Supplied chart does not match the pinned SHA256")
    regular(target)
    if target.exists():
        if digest_file(target) != expected:
            raise ArtifactError(f"Conflicting chart cache, preserved: {target}")
        return {"path": str(target), "sha256": expected, "cached": True}
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as f:
        tmp = Path(f.name)
    try:
        shutil.copyfile(source, tmp)
        publish_new(tmp, target, expected)
    finally:
        tmp.unlink(missing_ok=True)
    return {"path": str(target), "sha256": expected, "cached": False}


def chart(root, spec, supplied):
    target = relative(root, spec["path"])
    result = (copy_verified(Path(supplied).expanduser().resolve(), target, spec["sha256"])
              if supplied else fetch(spec["url"], target, spec["sha256"]))
    try:
        with tarfile.open(target, "r:gz") as archive:
            meta = archive.extractfile("dps/Chart.yaml")
            if meta is None:
                raise ArtifactError("Chart metadata missing")
            text = meta.read().decode()
        version = re.search(r"(?m)^version:\s*['\"]?([^\s'\"]+)", text)
        name = re.search(r"(?m)^name:\s*['\"]?([^\s'\"]+)", text)
        if not version or version.group(1) != spec["version"] or not name or name.group(1) != "dps":
            raise ArtifactError("Chart metadata is not DPS 0.9.0")
    except (tarfile.TarError, KeyError, UnicodeError) as exc:
        raise ArtifactError("Invalid DPS chart archive") from exc
    emit("chart-ready", version=spec["version"], sha256=spec["sha256"])
    return result


def run(args, timeout=900):
    proc = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout)
    if proc.returncode:
        raise ArtifactError(
            f"{args[0]} {args[1]} failed ({proc.returncode}):\n{proc.stdout[-6000:]}")
    return proc.stdout


def inspect(reference):
    proc = subprocess.run(["docker", "image", "inspect", reference],
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.returncode:
        return None
    return json.loads(proc.stdout)[0]


def pinned_image(reference):
    expected = reference.rsplit("@", 1)[-1]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
        raise ArtifactError("Image reference must contain a fixed SHA256 digest")
    info = inspect(reference)
    cached = info is not None
    if info is None:
        emit("image-pull", image_digest=reference)
        run(["docker", "pull", "--platform", "linux/amd64", reference])
        info = inspect(reference)
    if info is None or not any(x.endswith("@" + expected) for x in info.get("RepoDigests", [])):
        raise ArtifactError(f"Docker metadata digest mismatch: {reference}")
    if info.get("Architecture") != "amd64" or info.get("Os") != "linux":
        raise ArtifactError(f"Expected linux/amd64 image: {reference}")
    return {"image_digest": reference, "image_id": info["Id"], "cached": cached}


def image_set(spec):
    result = []
    for item in spec:
        observed = pinned_image(item["image_digest"])
        tag = item.get("tag")
        if tag:
            previous = inspect(tag)
            if previous is not None and previous["Id"] != observed["image_id"]:
                raise ArtifactError(f"Conflicting image tag, preserved: {tag}")
            if previous is None:
                run(["docker", "tag", observed["image_id"], tag])
        result.append({"name": item["name"], "tag": tag, **observed})
        emit("image-ready", name=item["name"], **observed)
    return result


def json_state(path, value):
    regular(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
    try:
        tmp.chmod(0o644)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def ldap_build(root, spec):
    build = relative(root, spec["build_directory"])
    public_build = ctx.source_path(spec["build_directory"])
    build.mkdir(parents=True, exist_ok=True)
    for filename in spec["recipe_sha256"]:
        original = public_build / filename
        target = build / filename
        regular(original); regular(target)
        if not original.is_file() or digest_file(original) != spec["recipe_sha256"][filename]:
            raise ArtifactError("Public LDAP recipe does not match its pinned checksum: " + filename)
        if target.exists() and digest_file(target) != digest_file(original):
            raise ArtifactError("Existing runtime LDAP recipe differs: " + filename)
        if not target.exists(): shutil.copy2(original, target)
    recipes = spec["recipe_sha256"]
    for name, expected in recipes.items():
        path = build / name
        regular(path)
        if not path.is_file() or digest_file(path) != expected:
            raise ArtifactError(f"Missing/conflicting tracked LDAP recipe: {name}")
    packages = []
    for item in spec["debs"]:
        if Path(item["filename"]).name != item["filename"]:
            raise ArtifactError("LDAP package filename must be a basename")
        result = fetch(item["url"], build / "debs" / item["filename"], item["sha256"])
        packages.append({"filename": item["filename"], "sha256": item["sha256"],
                         "cached": result["cached"]})
    for line in (build / "SHA256SUMS").read_text().splitlines():
        if line.strip():
            expected, name = line.split(None, 1)
            target = build / name.strip().lstrip("*")
            regular(target)
            if not target.is_file() or digest_file(target) != expected:
                raise ArtifactError(f"LDAP recipe SHA256SUMS mismatch: {name}")
    manifest_path = relative(root, spec["runtime_manifest"])
    regular(manifest_path)
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    fingerprint = hashlib.sha256(json.dumps({
        "base_image": spec["base_image"], "recipe_sha256": recipes,
        "debs": [{"filename": x["filename"], "sha256": x["sha256"]} for x in spec["debs"]],
        "platform": "linux/amd64"
    }, sort_keys=True).encode()).hexdigest()
    image = spec["image"]
    if image != "dps-openldap:2.6.10-bootstrap":
        raise ArtifactError("LDAP build may only use the dedicated bootstrap tag")
    info = inspect(image)
    if info is not None:
        labels = info.get("Config", {}).get("Labels") or {}
        if labels.get("com.nvidia.dps-deploy.ldap-recipe") != fingerprint:
            raise ArtifactError(f"Conflicting LDAP bootstrap tag, preserved: {image}")
    if previous and (previous.get("recipe_fingerprint") != fingerprint or
                     (info and previous.get("image_id") != info["Id"])):
        raise ArtifactError("Conflicting LDAP build metadata, preserved")
    if info is None:
        pinned_image(spec["base_image"])
        emit("ldap-build", image=image, recipe_fingerprint=fingerprint)
        run(["docker", "build", "--platform", "linux/amd64", "--network", "none",
             "--label", "com.nvidia.dps-deploy.ldap-recipe=" + fingerprint,
             "--tag", image, str(build)])
        info = inspect(image)
    if info is None:
        raise ArtifactError("LDAP build did not create an image")
    archive = relative(root, spec["archive"])
    regular(archive)
    if archive.exists():
        if (not previous or previous.get("image_id") != info["Id"] or
                digest_file(archive) != previous.get("archive_sha256")):
            raise ArtifactError(f"Conflicting LDAP archive, preserved: {archive}")
        archive_hash = previous["archive_sha256"]
    else:
        archive.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=archive.parent, delete=False) as f:
            tmp = Path(f.name)
        try:
            emit("ldap-save", archive=str(archive))
            run(["docker", "save", "--output", str(tmp), image])
            archive_hash = digest_file(tmp)
            publish_new(tmp, archive, archive_hash)
        finally:
            tmp.unlink(missing_ok=True)
    result = {
        "schema_version": 1, "image": image, "image_id": info["Id"],
        "platform": "linux/amd64", "slapd_version": spec["slapd_version"],
        "base_image": spec["base_image"], "recipe_sha256": recipes,
        "recipe_fingerprint": fingerprint, "archive": spec["archive"],
        "archive_sha256": archive_hash, "debs": packages,
        "built_at": (previous.get("built_at") if previous else
                     datetime.now(timezone.utc).isoformat()),
    }
    json_state(manifest_path, result)
    emit("ldap-ready", image=image, image_id=info["Id"], archive=str(archive),
         runtime_manifest=str(manifest_path))
    return result


def main():
    default_root = ctx.runtime_root
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--component", choices=("chart", "images", "ldap", "all"), default="all")
    parser.add_argument("--chart-file", help="Validate and cache an existing pinned DPS 0.9.0 chart")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = ctx.source_path("dps-install/config/artifact-sources.json")
    spec = json.loads(source.read_text())
    if spec.get("schema_version") != 1:
        raise ArtifactError("Unsupported artifact source schema")
    result = {"schema_version": 1, "checked_at": datetime.now(timezone.utc).isoformat(),
              "component": args.component, "root": str(root)}
    if args.component in ("chart", "all"):
        result["chart"] = chart(root, spec["chart"], args.chart_file)
    if args.component in ("images", "ldap", "all") and not shutil.which("docker"):
        raise ArtifactError("Docker is required for pinned image acquisition/LDAP build")
    if args.component in ("images", "all"):
        result["images"] = image_set(spec["images"])
    if args.component in ("ldap", "all"):
        result["ldap"] = ldap_build(root, spec["ldap"])
    state = root / "dps-install/config/artifacts-runtime.json"
    json_state(state, result)
    emit("artifacts-ready", component=args.component, state=str(state))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ArtifactError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"artifact acquisition stopped: {exc}", file=sys.stderr)
        sys.exit(1)
