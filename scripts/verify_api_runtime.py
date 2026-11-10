"""Bounded api HTTP/Docker recovery trial; retains its stopped dedicated volumes."""

import argparse
import hashlib
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from awm_adm.engine import read_snapshot
from awm_adm.runtime.protocol import pack

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.project.startswith("awm-adm-check-api-"):
        raise ValueError("Use a dedicated api project")
    args.output.mkdir(parents=True, exist_ok=False)
    compose = ["docker", "compose", "-p", args.project]
    records = []
    checks = []
    owner = (ROOT / ".local/secrets/owner-token").read_text().strip()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def command(command, timeout=75):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        records.append(
            {
                "command": command,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    def api(path, body=None, *, method=None, token=None, expected=200, headers=None):
        headers = {"Authorization": "Bearer " + (token or owner), **(headers or {})}
        raw = json.dumps(body).encode() if body is not None else None
        if raw:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            "http://127.0.0.1:8080/api/v1" + path,
            data=raw,
            headers=headers,
            method=method or ("POST" if raw is not None else "GET"),
        )
        try:
            with opener.open(request, timeout=20) as response:
                status = response.status
                data = response.read(4_194_304)
        except urllib.error.HTTPError as error:
            status = error.code
            data = error.read(65_536)
        assert status == expected, (path, status, data[:500])
        return json.loads(data)

    def wait(path):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            value = api(path)
            if value["status"] not in ("received", "running", "evaluating"):
                return value
            time.sleep(0.05)
        raise AssertionError("Bounded trial operation did not complete")

    def create(name, snapshot=None):
        body = {"idempotency_key": "create-" + name, "name": name}
        if snapshot:
            body["snapshot"] = pack(read_snapshot(ROOT / "tests/fixtures/v1/reference" / snapshot))
        op = api("/adms", body, expected=202)
        done = wait("/operations/" + op["operation_id"])
        assert done["status"] == "succeeded", done
        return done["result"]["adm_id"]

    def query(key, uid, query):
        path = "/adms/" + key + "/requests"
        record = api(path, {"idempotency_key": uid, "query": query}, expected=202)
        return wait(path + "/" + record["request_id"])

    def check(name):
        checks.append(name)
        print(name, flush=True)

    status = "failed"
    try:
        command([*compose, "up", "-d", "--no-build", "--wait", "--wait-timeout", "60"])
        ids = command([*compose, "ps", "-q"]).split()
        inspected = json.loads(command(["docker", "inspect", *ids]))
        for item in inspected:
            role = item["Config"]["Labels"]["com.docker.compose.service"]
            assert item["Config"]["User"] == "10001:10001" and item["HostConfig"]["ReadonlyRootfs"]
            assert item["HostConfig"]["Memory"] > 0 and "ALL" in item["HostConfig"]["CapDrop"]
            if role == "app":
                assert item["NetworkSettings"]["Ports"]["8080/tcp"] == [
                    {"HostIp": "127.0.0.1", "HostPort": "8080"}
                ]
            else:
                assert not item["HostConfig"]["PortBindings"]
                assert all(m["Destination"] != "/var/lib/awm-adm" for m in item["Mounts"])
            probe = "import socket,json\ntry: s=socket.create_connection(('1.1.1.1',443),timeout=2); s.close(); ok=True\nexcept OSError: ok=False\nprint(json.dumps({'connected':ok}))"
            result = json.loads(command([*compose, "exec", "-T", role, "python", "-c", probe]))
            assert result["connected"] == (role == "provider-gateway")
        probe = "import socket,json\ntry: s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.close(); denied=False\nexcept PermissionError: denied=True\nprint(json.dumps({'denied':denied}))"
        assert json.loads(command([*compose, "exec", "-T", "app", "python", "-c", probe]))["denied"]
        check("nonroot_private_storage_loopback_publication_and_network_restrictions")
        with opener.open("http://127.0.0.1:8080/") as response:
            html = response.read()
        assets = []
        for path in re.findall(rb'(?:src|href)="(/assets/[^\"]+)"', html):
            with opener.open("http://127.0.0.1:8080" + path.decode()) as response:
                data = response.read()
                assert len(data) == int(response.headers["Content-Length"])
            assert data == (ROOT / "console/dist" / path.decode().lstrip("/")).read_bytes()
            assets.append(
                {"path": path.decode(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            )
        (args.output / "assets.json").write_text(json.dumps(assets, indent=2) + "\n")
        api("/adms", token="invalid", expected=401)
        key = create("tanks", "tanks.adm")
        access = create("access", "access.adm")
        empty = create("empty")
        path = "/adms/" + key
        plan = {
            "op": "find_plan",
            "module": "tanks",
            "initial_state": {"left": 0, "right": 0},
            "goal": "tanks.four_litres",
        }
        body = {"idempotency_key": "parallel-retry", "query": plan}
        with ThreadPoolExecutor(max_workers=4) as pool:
            posted = list(pool.map(lambda _: api(path + "/requests", body, expected=202), range(8)))
        assert len({r["request_id"] for r in posted}) == 1
        uid = posted[0]["request_id"]
        done = wait(path + "/requests/" + uid)
        assert done["status"] == "succeeded" and done["result"]["value"]["steps"] == 6
        api(path + "/requests", {**body, "query": {**plan, "max_depth": 0}}, expected=409)
        api("/adms/" + empty + "/requests/" + uid, expected=404)
        check("host_assets_authenticated_creation_concurrent_idempotency_and_local_plan")
        credential = api("/auth/tokens", {"adms": [key], "permissions": ["read", "submit"]})
        api("/adms/" + access, token=credential["token"], expected=403)
        api(
            path + "/settings",
            {"expected_epoch": 0, "mode": "forward"},
            method="PATCH",
            token=credential["token"],
            expected=403,
        )
        api("/auth/tokens/" + credential["id"], method="DELETE")
        api(path, token=credential["token"], expected=401)
        check("per_adm_client_scope_owner_authority_and_revocation")
        cert = json.loads((ROOT / "tests/fixtures/v1/certificates/access-unreachable.json").read_text())
        proof = {"op": "check_certificate", "certificate": cert, "backend": "lean"}
        checked = query(access, "proof", proof)
        assert (
            checked["result"]["lean_kernel"] == "checked"
            and checked["result"]["exhaustive_finite"] == "checked"
        )
        command([*compose, "stop", "learning-worker", "provider-gateway"])
        assert query(key, "offline", plan)["status"] == "succeeded"
        assert query(access, "offline-proof", proof)["result"]["lean_kernel"] == "checked"
        check("two_domains_and_linux_lean_with_components_stopped")
        before = api(path + "/events")
        cursor = before["cursor"]
        consumer1 = api(path + "/event-consumers", {"cursor": 0})
        consumer2 = api(path + "/event-consumers", {"cursor": 0})
        api(path + "/event-consumers/" + consumer1["id"] + "/cursor", {"cursor": cursor}, method="PUT")
        assert (
            api(path + "/event-consumers/" + consumer2["id"] + "/cursor", {"cursor": 1}, method="PUT")[
                "cursor"
            ]
            == 1
        )
        request = urllib.request.Request(
            "http://127.0.0.1:8080/api/v1" + path + "/events?once=true",
            headers={
                "Authorization": "Bearer " + owner,
                "Accept": "text/event-stream",
                "Last-Event-ID": key + ":1",
            },
        )
        with opener.open(request, timeout=5) as response:
            sse = response.read().decode()
        assert "request.succeeded" in sse and f"id: {key}:1\n" not in sse
        (args.output / "events.sse").write_text(sse)
        api(path + "/events/prune", {"cursor": 1})
        api(path + "/events?after=0", expected=410)
        check("independent_consumers_sse_replay_and_expired_cursor_resync")
        changed = api(path + "/settings", {"expected_epoch": 0, "mode": "forward"}, method="PATCH")
        assert changed["policy_epoch"] == 1
        api(path + "/settings", {"expected_epoch": 0, "mode": "backward"}, method="PATCH", expected=409)
        assert api(path + "/requests/" + uid)["result"] == done["result"]
        export = api(path + "/snapshot-exports", {"idempotency_key": "export"}, expected=202)
        package = wait("/operations/" + export["operation_id"])["result"]["snapshot"]
        restored = api(
            "/adms",
            {"idempotency_key": "clone", "name": "clone", "snapshot": package},
            expected=202,
        )
        clone = wait("/operations/" + restored["operation_id"])["result"]["adm_id"]
        assert clone != key and query(clone, "clone-plan", plan)["result"]["value"]["steps"] == 6
        check("future_mode_epoch_historical_result_and_independent_snapshot_clone")

        # Pause an actual child before cancellation, then repeat for app SIGKILL.
        watcher_code = """
import os,signal,time,sys
from pathlib import Path
end=time.monotonic()+8
while time.monotonic()<end:
 for p in Path('/proc').glob('[0-9]*/cmdline'):
  try: command=p.read_bytes()
  except OSError: continue
  if b'awm_adm.runtime.compute' in command.split(b'\\0'):
   os.kill(int(p.parent.name),signal.SIGSTOP);print(p.parent.name,flush=True);sys.exit(0)
 time.sleep(.005)
sys.exit(2)
"""
        for kind in ("cancel", "kill"):
            watcher = subprocess.Popen(
                [*compose, "exec", "-T", "app", "python", "-c", watcher_code],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            record = api(
                "/adms/" + access + "/requests", {"idempotency_key": kind, "query": proof}, expected=202
            )
            output, error = watcher.communicate(timeout=12)
            assert watcher.returncode == 0, error
            request_path = "/adms/" + access + "/requests/" + record["request_id"]
            if kind == "cancel":
                assert api(request_path + "/cancel", method="POST")["status"] == "cancelled"
                assert query(key, "while-cancel", plan)["status"] == "succeeded"
                assert api(request_path)["result"] is None
            else:
                command([*compose, "kill", "-s", "SIGKILL", "app"])
                command([*compose, "up", "-d", "--no-build", "--wait", "--wait-timeout", "60"])
                interrupted = api(request_path)
                assert interrupted["status"] == "inconclusive" and interrupted["result"] is None
                api(request_path + "/retry", method="POST", expected=202)
                retried = wait(request_path)
                assert retried["status"] == "succeeded" and len(retried["attempts"]) == 2
        check("real_child_cancellation_app_sigkill_reclaim_and_explicit_retry")
        assert api(path)["mode"] == "forward"
        assert api(path + "/requests/" + uid)["result"] == done["result"]
        api("/adms/" + empty + "/archive", {"expected_epoch": 0})
        api(
            "/adms/" + empty + "/requests",
            {"idempotency_key": "archived", "query": {"op": "capabilities"}},
            expected=409,
        )
        check("restart_preserves_mode_results_and_archive_fences_new_work")
        (args.output / "instances.json").write_text(
            json.dumps(
                {"tanks": key, "access": access, "empty": empty, "clone": clone, "original_request": uid},
                indent=2,
            )
            + "\n"
        )
        (args.output / "openapi.json").write_text(json.dumps(api("/openapi.json"), indent=2) + "\n")
        status = "passed"
    finally:
        try:
            command([*compose, "logs", "--no-color", "--tail", "100"])
            command([*compose, "stop"])
        finally:
            (args.output / "report.json").write_text(
                json.dumps(
                    {
                        "status": status,
                        "checks": checks,
                        "commands": records,
                        "live_provider_calls": 0,
                        "volumes_preserved": True,
                        "credentials_logged": False,
                    },
                    indent=2,
                )
                + "\n"
            )


if __name__ == "__main__":
    main()
