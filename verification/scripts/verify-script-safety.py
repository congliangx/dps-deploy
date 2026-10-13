#!/usr/bin/env python3
"""Run offline script safety regressions using temporary public fixtures and mocks.

No deployment, image pull/import, service change, login or BMC request is made.
Reports and temporary fixtures belong to the selected runtime, never source.
"""
import sys
sys.dont_write_bytecode = True
import argparse, contextlib, io, json, os, re, runpy
import shlex, shutil, socket, ssl, subprocess, tempfile, types, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]


class FixtureContext:
    def __init__(self, source, runtime, settings):
        self.source_root, self.runtime_root, self.settings = source, runtime, settings
    def source_path(self, relative):
        return self.source_root / relative
    def runtime_path(self, relative):
        return self.runtime_root / relative


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", "--deployment-config", help="Public deployment settings")
    parser.add_argument("--runtime-root", help="Override the report/temporary fixture directory")
    args = parser.parse_args()
    sys.path.insert(0, str(SOURCE / "dps-install/scripts"))
    from deployment_context import load_context
    import yaml
    ctx = load_context(config_path=args.config, runtime_root=args.runtime_root)
    archive = ctx.runtime_path("verification/archive/script-safety")
    archive.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []

    def case(name, action):
        try:
            action()
            results.append({"name": name, "passed": True})
        except Exception as error:
            results.append({"name": name, "passed": False, "error_type": type(error).__name__,
                            "detail": str(error)[:500]})

    with tempfile.TemporaryDirectory(prefix="run-", dir=archive) as temporary:
        root = Path(temporary)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("DPS_", "DPSCTL_", "HELM_", "KUBE"))}
        traps = root / "bin"; traps.mkdir()
        trace = root / "external-command-trap.log"
        for name, target in (("python3", sys.executable), ("bash", "/bin/bash"), ("dirname", shutil.which("dirname"))):
            (traps / name).symlink_to(target)
        commands = ("docker k3s kubectl helm systemctl curl wget apt-get openssl git ss jq "
                    "ldapwhoami dpsctl rm mv cp chmod chown install mkdir tee seq sleep").split()
        for name in commands:
            path = traps / name
            path.write_text('#!/bin/bash\nprintf "%s\\n" "$0" >> "$DPS_SAFETY_TRACE"\nexit 97\n')
            path.chmod(0o700)
        env.update(PATH=str(traps), DPS_SAFETY_TRACE=str(trace), PYTHONDONTWRITEBYTECODE="1")
        settings = dict(ctx.settings)
        runtime_a, runtime_b = root / "runtime-a", root / "runtime-b"
        configs = []
        for runtime in (runtime_a, runtime_b):
            runtime.mkdir()
            (runtime / "dps-install/packages/tools/bin").mkdir(parents=True)
            config = root / (runtime.name + ".yaml")
            config.write_text(yaml.safe_dump({**settings, "runtime_root": str(runtime)}))
            configs.append(config)
        missing = root / "missing.yaml"

        def shell(path, argv, expected=2):
            trace.unlink(missing_ok=True)
            result = subprocess.run(["/bin/bash", str(path), *argv], env=env,
                                    text=True, capture_output=True, timeout=30)
            assert result.returncode == expected, (path.name, result.returncode, result.stderr[:250])
            assert not trace.exists(), "An external action was reached: " + path.name
        entries = sorted(p for folder in ("dps-install/scripts", "hardware-sim/scripts", "verification/scripts")
                         for p in ctx.source_path(folder).glob("*.sh") if p.name != "deployment-env.sh")
        for path in entries:
            for flag in ("--help", "-h"):
                case(path.name + " " + flag + " with absent config", lambda p=path, f=flag:
                     shell(p, [f, "--config", str(missing)], 0))
            case(path.name + " rejects unexpected parameter", lambda p=path:
                 shell(p, ["--config", str(configs[0]), "--unexpected-safety=value"]))
        for relative in ("hardware-sim/scripts/bmc-simulator.sh", "dps-install/scripts/kubernetes.sh"):
            case(Path(relative).name + " rejects extra action argument", lambda r=relative:
                 shell(ctx.source_path(r), ["--config", str(configs[0]), "status", "extra"]))

        def path_order():
            loader = shlex.quote(str(ctx.source_path("dps-install/scripts/deployment-env.sh")))
            lines = []
            for config in (configs[0], configs[0], configs[1], configs[0]):
                lines += ["source " + loader + " --config " + shlex.quote(str(config)), 'printf "%s\\n" "$PATH"']
            trace.unlink(missing_ok=True)
            result = subprocess.run(["/bin/bash", "-c", "\n".join(lines)], env=env,
                                    text=True, capture_output=True, timeout=30)
            assert result.returncode == 0, result.stderr[:250]
            assert not trace.exists()
            paths = result.stdout.splitlines()
            for value, runtime in zip(paths, (runtime_a, runtime_a, runtime_b, runtime_a)):
                expected = str(runtime / "dps-install/packages/tools/bin")
                assert value.split(":")[0] == expected and value.split(":").count(expected) == 1
            assert len(paths) == 4
        case("environment source A/A/B/A keeps selected tools first without duplicates", path_order)

        calls = []
        fixture = FixtureContext(ctx.source_root, root / "python-fixture", settings)
        fixture.runtime_root.mkdir()
        context_module = types.ModuleType("deployment_context")
        context_module.context_from_cli = lambda: fixture
        context_module.load_context = lambda: fixture

        def execute(relative, argv=(), run=None, network=None):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.dict(sys.modules, {"deployment_context": context_module}))
                stack.enter_context(mock.patch.object(sys, "argv", [relative, *argv]))
                stack.enter_context(mock.patch("subprocess.run", side_effect=run or (lambda *a, **kw:
                    (_ for _ in ()).throw(AssertionError("Unexpected subprocess")))))
                stack.enter_context(mock.patch("urllib.request.urlopen", side_effect=network or (lambda *a, **kw:
                    (_ for _ in ()).throw(AssertionError("Unexpected network request")))))
                stack.enter_context(mock.patch("socket.socket", side_effect=AssertionError("Unexpected socket")))
                stack.enter_context(contextlib.redirect_stdout(stdout))
                stack.enter_context(contextlib.redirect_stderr(stderr))
                code = 0
                try:
                    runpy.run_path(str(fixture.source_path(relative)), run_name="__main__")
                except SystemExit as error:
                    code = error.code
                return code, stdout.getvalue(), stderr.getvalue()
        stages = ("dps-install/scripts/stage-runtime-images.py", "dps-install/scripts/stage-prs-images.py",
                  "verification/scripts/stage-probe-images.py", "verification/scripts/verify-bmc.py")
        for relative in stages:
            case(Path(relative).name + " safe help", lambda r=relative:
                 assert_exit(execute(r, ["--help", "--config", str(missing)]), 0))
            case(Path(relative).name + " rejects unknown argument without actions", lambda r=relative:
                 assert_exit(execute(r, ["--unexpected-safety"]), 2))
        def no_control():
            before = list(fixture.runtime_root.rglob("*"))
            result = execute("verification/scripts/verify-bmc.py")
            assert_exit(result, 2)
            assert not result[1] and list(fixture.runtime_root.rglob("*")) == before
        case("BMC control requires explicit opt-in before outputs or requests", no_control)

        pins = json.loads(ctx.source_path("dps-install/config/artifact-sources.json").read_text())["images"]
        by_digest = {row["image_digest"]: row for row in pins}
        by_tag = {row["tag"]: row for row in pins if row.get("tag")}
        stale = False
        def stage_run(argv, **kwargs):
            command = [str(x) for x in argv]; calls.append(command)
            output = ""
            if command[:3] == ["docker", "image", "inspect"]:
                ref = command[-1]; row = by_digest.get(ref) or by_tag[ref]
                identity = "offline-image-" + str(pins.index(row))
                if stale and "@" not in ref: identity = "offline-conflict"
                output = json.dumps([{"Id": identity, "Architecture": "amd64", "Os": "linux",
                                     "RepoDigests": [row["image_digest"]]}])
            elif command[:2] == ["docker", "save"]:
                Path(command[command.index("--output") + 1]).write_bytes(b"offline image archive")
            elif command[0] not in ("systemctl", "k3s"):
                raise AssertionError("Unexpected stage action")
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")
        def stale_pin():
            nonlocal stale
            calls.clear(); stale = True
            try:
                try: execute("dps-install/scripts/stage-prs-images.py", run=stage_run)
                except RuntimeError: pass
                else: raise AssertionError("Wrong tag identity was accepted")
                assert not any(command[0] == "k3s" or command[:2] in (["docker", "pull"], ["docker", "save"])
                               for command in calls)
            finally: stale = False
        case("PRS wrong tag image ID rejected before save/import", stale_pin)
        def pinned_stage(relative):
            calls.clear(); assert_exit(execute(relative, run=stage_run), 0)
            assert any(command[0] == "k3s" for command in calls)
            assert not any(command[:2] == ["docker", "pull"] for command in calls)
        case("PRS fixed digests stage successfully with mocked containerd", lambda:
             pinned_stage("dps-install/scripts/stage-prs-images.py"))
        def corrupt_archive():
            path = fixture.runtime_path("dps-install/packages/prs/prs-2.1.0-runtime.tar")
            path.write_bytes(b"changed offline archive"); before = path.read_bytes(); calls.clear()
            try: execute("dps-install/scripts/stage-prs-images.py", run=stage_run)
            except RuntimeError: pass
            else: raise AssertionError("Changed archive hash was accepted")
            assert path.read_bytes() == before and not any(command[0] == "k3s" for command in calls)
        case("PRS existing archive hash conflict preserves archive and blocks import", corrupt_archive)
        case("DPS fixed digests stage successfully with mocks", lambda:
             pinned_stage("dps-install/scripts/stage-runtime-images.py"))
        def same_root():
            nonlocal fixture
            earlier = fixture; source = root / "same-root"
            tracked = ("dps-install/scripts/download-artifacts.py", "dps-install/scripts/stage-prs-images.py",
                       "dps-install/config/artifact-sources.json", "dps-install/config/values.example.yaml")
            for relative in tracked:
                target = source / relative; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ctx.source_path(relative), target)
            before = {relative: (source / relative).read_bytes() for relative in tracked}
            fixture = FixtureContext(source, source, settings)
            try: pinned_stage("dps-install/scripts/stage-prs-images.py")
            finally: fixture = earlier
            assert all((source / relative).read_bytes() == value for relative, value in before.items())
        case("same-root staging preserves checked-in source inputs", same_root)

        # Shared UI recovery must remain tied to the selected deployment and saved inputs.
        shared_body = re.search(r"<<'PREFLIGHT'\n(.*?)\nPREFLIGHT", ctx.source_path(
            "dps-install/scripts/shared-ui-start.sh").read_text(), re.S).group(1)

        def shared_ui_preflight(mode):
            import hashlib
            selected = root / ("shared-ui-" + mode)
            selected.mkdir()
            same = mode == "same-root"
            selected_source = selected if same else ctx.source_root
            selected_runtime = selected if same else selected / "runtime"
            selected_runtime.mkdir(exist_ok=True)
            artifact_relative = "dps-install/config/artifact-sources.json"
            if same:
                target = selected_source / artifact_relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ctx.source_path(artifact_relative), target)
            artifact = selected_source / artifact_relative
            before_artifact = artifact.read_bytes()
            access = selected_runtime / "dps-install/config/access/shared-ui"
            tls = selected_runtime / "dps-install/config/tls"
            access.mkdir(parents=True); tls.mkdir(parents=True, exist_ok=True)
            for name in ("ingress.crt", "ingress.key", "ca.crt"):
                (tls / name).write_bytes(b"offline public test fixture")
            pin = next(row["image_digest"] for row in pins if row["name"] == "nginx-proxy")
            image_id = "offline-shared-ui-image"
            selected_host = "192.0.2.23"
            project = "offline-lab-dps-ui-access"
            service_uid = "offline-ui-service"
            upstream = "http://192.0.2.90:80"
            metadata = {"compose_project": project, "container": project, "image_digest": pin,
                        "image_id": image_id, "public_ca_sha256": hashlib.sha256(
                            (tls / "ca.crt").read_bytes()).hexdigest(),
                        "url": "https://" + selected_host + ":9443", "upstream": upstream}
            labels = {"com.nvidia.dps.runtime-root": str(selected_runtime),
                      "com.nvidia.dps.source-service-uid": service_uid}
            volumes = [str(access / "nginx.conf") + ":/etc/nginx/nginx.conf:ro"]
            volumes += [str(tls / name) + ":/etc/dps-ui-tls/" + name + ":ro"
                        for name in ("ingress.crt", "ingress.key", "ca.crt")]
            if mode == "relative-mounts":
                volumes = ["nginx.conf:/etc/nginx/nginx.conf:ro"] + [
                    "../../tls/" + name + ":/etc/dps-ui-tls/" + name + ":ro"
                    for name in ("ingress.crt", "ingress.key", "ca.crt")]
            if mode == "saved-image-conflict":
                metadata["image_digest"] = "nginx@sha256:" + "0" * 64
            if mode == "wrong-release":
                metadata["compose_project"] = metadata["container"] = "another-release-ui-access"
            if mode == "wrong-host":
                metadata["url"] = "https://192.0.2.24:9443"
            (access / "access.json").write_text(json.dumps(metadata))
            (access / "compose.yaml").write_text(yaml.safe_dump({"services": {"ui-access": {
                "image": metadata["image_digest"], "container_name": metadata["container"],
                "network_mode": "host", "labels": labels, "volumes": volumes}}}))
            (access / "nginx.conf").write_text("listen 192.0.2.23:9443 ssl;\nproxy_pass " + upstream + ";\n")
            if mode == "changed-ca":
                (tls / "ca.crt").write_bytes(b"changed offline CA")
            original_inputs = {p: p.read_bytes() for p in [*access.iterdir(), *tls.iterdir()]}
            shared_calls = []

            def read_command(argv, **kwargs):
                argv = list(argv); shared_calls.append(argv)
                if argv[:3] == ["docker", "image", "inspect"]:
                    return json.dumps([{"Id": image_id, "RepoDigests": [] if mode == "cached-digest-conflict" else [pin]}])
                assert argv[0] == "kubectl" and "get" in argv and "service" in argv
                assert argv[argv.index("--context") + 1] == "offline-context"
                assert argv[argv.index("-n") + 1] == "offline-namespace"
                assert argv[argv.index("service") + 1] == "offline-lab-dps-ui"
                return json.dumps({"metadata": {"uid": "changed-service" if mode == "stale-service-uid" else service_uid},
                    "spec": {"clusterIP": "192.0.2.91" if mode == "stale-service-ip" else "192.0.2.90",
                             "ports": [{"port": 80}]}})

            def inspect_command(argv, **kwargs):
                argv = list(argv); shared_calls.append(argv)
                assert argv == ["docker", "inspect", project]
                owned = {"com.docker.compose.project": "foreign-project" if mode == "foreign-container" else project,
                         "com.nvidia.dps.purpose": "shared-ui-access",
                         "com.nvidia.dps.runtime-root": str(selected_runtime)}
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps([{"Config": {"Labels": owned}}]), stderr="")

            public_environment = {"DPS_SOURCE_ROOT": str(selected_source), "DPS_RUNTIME_ROOT": str(selected_runtime),
                "DPS_RELEASE": "offline-lab-dps", "DPS_HOST_IP": selected_host, "DPS_FULLNAME": "offline-lab-dps",
                "DPS_NAMESPACE": "offline-namespace", "DPS_KUBE_CONTEXT": "offline-context",
                "KUBECONFIG": str(selected_runtime / "dps-install/config/kubernetes/kubeconfig.yaml")}
            captured = io.StringIO(); failure = None
            with mock.patch.dict(os.environ, public_environment), mock.patch.object(sys, "argv", ["preflight", str(access)]), \
                    mock.patch("subprocess.check_output", side_effect=read_command), \
                    mock.patch("subprocess.run", side_effect=inspect_command), contextlib.redirect_stdout(captured):
                try: exec(compile(shared_body, "shared UI preflight fixture", "exec"), {})
                except SystemExit as error: failure = str(error.code)
            errors = {"saved-image-conflict": "canonical", "cached-digest-conflict": "RepoDigest",
                      "wrong-release": "different release", "wrong-host": "host differs",
                      "changed-ca": "Public CA", "stale-service-uid": "identity changed",
                      "stale-service-ip": "ClusterIP changed", "foreign-container": "another Compose project"}
            if mode in errors:
                assert failure and errors[mode] in failure, (mode, failure)
            else:
                assert failure is None, failure
                parameters = captured.getvalue().splitlines()
                assert len(parameters) == 7 and parameters[:3] == [project, project, metadata["url"]]
                assert parameters[3] == str(tls / "ca.crt") and parameters[6] == selected_host
            assert all(path.read_bytes() == value for path, value in original_inputs.items())
            assert artifact.read_bytes() == before_artifact
            assert all(argv[0] == "kubectl" or argv[:2] == ["docker", "inspect"] or argv[:3] == ["docker", "image", "inspect"]
                       for argv in shared_calls)

        for mode in ("different-instance", "same-root", "relative-mounts", "saved-image-conflict",
                     "cached-digest-conflict", "wrong-release", "wrong-host", "changed-ca",
                     "stale-service-uid", "stale-service-ip", "foreign-container"):
            case("shared UI preflight " + mode + " preserves input files and avoids mutations",
                 lambda m=mode: shared_ui_preflight(m))

        body = re.search(r"<<'PYTHON'\n(.*?)\nPYTHON", ctx.source_path(
            "dps-install/scripts/prepare-namespace.sh").read_text(), re.S).group(1)
        config = fixture.runtime_path("dps-install/config")
        config.mkdir(parents=True, exist_ok=True)
        (config / "values.yaml").write_text(yaml.safe_dump({"dps": {"ldap": {"enabled": False}, "prs": {"enabled": False}}}))
        filenames = ["postgresql-secret.yaml", "postgresql-ca-secret.yaml", "bmc-shared-secret.yaml", "bmc-ca-secret.yaml"]
        filenames += ["tls/" + name + ".yaml" for name in
                      ("dps-server-tls-secret", "dps-agent-tls-secret", "dps-ingress-tls-secret", "dps-jwt-keys-secret")]
        for name in filenames:
            path = config / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump({"kind": "Secret", "metadata": {"name": path.stem, "namespace": settings["namespace"]}}))
        hosts = root / "hosts"; hosts.write_text("127.0.0.1 localhost\n")
        def namespace_check(mode):
            calls.clear()
            fake_path = types.ModuleType("pathlib")
            fake_path.Path = lambda value: hosts if str(value) == "/etc/hosts" else Path(value)
            fake_socket = types.SimpleNamespace(AF_INET=socket.AF_INET, gaierror=socket.gaierror,
                getaddrinfo=lambda *a: [(2, 1, 6, "", ("192.0.2.9" if mode == "dns" else settings["host_ip"], 0))])
            def run(argv, **kwargs):
                calls.append(argv)
                if "namespace" in argv and "get" in argv:
                    return subprocess.CompletedProcess(argv, 1 if mode == "forbidden" else 0, stdout="{}", stderr="")
                output = json.dumps({"type": "Opaque", "stringData": {"offline-key": ""}}) if mode == "secret" and "get" in argv else ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")
            with mock.patch.dict(sys.modules, {"deployment_context": context_module, "pathlib": fake_path,
                                              "socket": fake_socket}), mock.patch("subprocess.run", side_effect=run), \
                    contextlib.redirect_stdout(io.StringIO()):
                try: exec(compile(body, "prepare-namespace fixture", "exec"), {})
                except SystemExit:
                    assert mode != "ok"
                else: assert mode == "ok"
            if mode == "ok": assert sum("apply" in command for command in calls) == len(filenames)
            else: assert not any("apply" in command or "create" in command for command in calls)
            if mode == "dns": assert not calls
        for mode in ("dns", "forbidden", "secret", "ok"):
            case("namespace " + mode + " preflight prevents unintended writes", lambda m=mode: namespace_check(m))

        def bmc_restore(fail_first=False):
            nodes = [{"node_id": "offline-node-" + str(i), "bmc_url": "https://offline-" + str(i) + ".invalid"} for i in range(72)]
            node_file = fixture.runtime_path("hardware-sim/runtime/nodes.json")
            node_file.parent.mkdir(parents=True, exist_ok=True); node_file.write_text(json.dumps(nodes))
            fixture.runtime_path("dps-install/config/bmc-credentials.json").write_text(json.dumps({"username": "", "password": ""}))
            states = {node["bmc_url"]: 1000 for node in nodes}; restored = []
            class Reply:
                status, headers = 200, {}
                def __init__(self, value): self.value = value
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self): return json.dumps(self.value).encode()
            def network(request, **kwargs):
                assert kwargs.get("context") is sentinel
                node = request.full_url.split("/redfish/", 1)[0]
                if request.get_method() == "PATCH":
                    value = json.loads(request.data)["PowerLimitWatts"]["SetPoint"]
                    if value == 1000:
                        restored.append(node)
                        if fail_first and node == nodes[0]["bmc_url"]: raise OSError("offline restore failure")
                    states[node] = value
                return Reply({"PowerLimitWatts": {"SetPoint": states.get(node, 1000)}})
            sentinel = object()
            def ca_context(*args, **kwargs):
                assert kwargs["cafile"] == str(fixture.runtime_path("dps-install/config/simulator-ca.crt"))
                return sentinel
            with mock.patch("ssl.create_default_context", side_effect=ca_context), \
                    mock.patch("ssl._create_unverified_context", side_effect=AssertionError("TLS bypass")):
                try: assert_exit(execute("verification/scripts/verify-bmc.py", ["--control"], network=network), 0)
                except AssertionError:
                    assert fail_first
                else: assert not fail_first
            report = json.loads(fixture.runtime_path("verification/reports/verification-control.json").read_text())
            assert len(restored) == 72 and len(set(restored)) == 72
            assert all(states[node["bmc_url"]] == 1000 for node in nodes[1:])
            assert report["checks"]["power_restore"]["all_restored"] is (not fail_first)
        case("BMC strict-CA mock restores all 72 changed limits", bmc_restore)
        case("BMC first restore failure still attempts the other 71 nodes", lambda: bmc_restore(True))

    report = ctx.runtime_path("verification/reports/script-safety-regression.json")
    report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    summary = {"time_utc": datetime.now(timezone.utc).isoformat(), "offline": True,
               "passed": sum(row["passed"] for row in results), "total": len(results), "cases": results,
               "actual_deployment_actions": False, "actual_network_requests": False}
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n"); report.chmod(0o600)
    print(json.dumps({"passed": summary["passed"], "total": summary["total"], "report": str(report)}))
    return 0 if summary["passed"] == summary["total"] else 1


def assert_exit(result, expected):
    assert result[0] == expected, (result[0], result[2][:250])


if __name__ == "__main__":
    raise SystemExit(main())
