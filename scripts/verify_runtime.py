"""Bounded Docker runtime trial. Uses a named trial stack; preserves its stopped volumes."""

import argparse
import hashlib
import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from awm_adm.engine import Instance, build_certificate, read_snapshot
from awm_adm.runtime.protocol import pack

ROOT = Path(__file__).resolve().parents[1]
RPC = """
import json,sys,urllib.error
from awm_adm.runtime.component import exchange
from awm_adm.runtime.http import secret
data=json.load(sys.stdin)
try:
 result=exchange('http://app:8081'+data['path'],secret('/run/secrets/'+data.get('role','owner')+'-token'),data.get('body'),timeout=15)
 print(json.dumps({'status':200,'body':result}))
except urllib.error.HTTPError as error:
 print(json.dumps({'status':error.code,'body':json.loads(error.read(65536))}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.project.startswith("awm-adm-check-runtime-"):
        raise ValueError("Use a dedicated awm-adm-check-runtime-* trial project")
    args.output.mkdir(parents=True, exist_ok=False)
    commands, checks = [], []
    compose = ["docker", "compose", "-p", args.project]
    operator = [*compose, "run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "operator", "-c", RPC]

    def run(arguments, *, input=None, timeout=60):
        result = subprocess.run(
            arguments, cwd=ROOT, input=input, capture_output=True, text=True, timeout=timeout
        )
        entry = {
            "command": arguments,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        commands.append(entry)
        if result.returncode:
            raise RuntimeError("Trial command failed: " + " ".join(arguments[:5]))
        return result.stdout

    def rpc(path, body=None, *, role="owner", expected=200):
        response = json.loads(
            run(
                operator
                if role == "owner"
                else [
                    *compose,
                    "exec",
                    "-T",
                    "learning-worker" if role == "worker" else "provider-gateway",
                    "python",
                    "-c",
                    RPC,
                ],
                input=json.dumps({"path": path, "body": body, "role": role}),
            )
        )
        assert response["status"] == expected, response
        return response["body"]

    def check(name):
        checks.append(name)
        print(name, flush=True)

    try:
        run([*compose, "up", "-d", "--wait", "--wait-timeout", "60"], timeout=75)
        config = json.loads(run([*compose, "config", "--format", "json"]))
        ids = run([*compose, "ps", "-q"]).split()
        inspected = json.loads(run(["docker", "inspect", *ids]))
        by_role = {item["Config"]["Labels"]["com.docker.compose.service"]: item for item in inspected}
        for role, item in by_role.items():
            assert item["Config"]["User"] == "10001:10001"
            assert item["HostConfig"]["ReadonlyRootfs"]
            assert item["HostConfig"]["Memory"] > 0 and item["HostConfig"]["PidsLimit"] > 0
            assert "ALL" in item["HostConfig"]["CapDrop"]
            ports = item["HostConfig"]["PortBindings"] or {}
            assert ports == (
                {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]} if role == "app" else {}
            )
        assert all(
            m["Destination"] != "/var/lib/awm-adm"
            for role in ("learning-worker", "provider-gateway")
            for m in by_role[role]["Mounts"]
        )
        assert config["networks"]["internal"]["internal"] is True
        assert by_role["app"]["NetworkSettings"]["Ports"]["8080/tcp"] == [
            {"HostIp": "127.0.0.1", "HostPort": "8080"}
        ]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:8080/health/ready", timeout=3) as response:
            assert json.load(response)["status"] == "ready"
        with opener.open("http://127.0.0.1:8080/", timeout=3) as response:
            html = response.read(65536)
            assert b'<div id="root">' in html
        assets = re.findall(rb'(?:src|href)="(/assets/[^\"]+)"', html)
        assert any(asset.endswith(b".js") for asset in assets)
        asset_records = []
        for asset in assets:
            with opener.open("http://127.0.0.1:8080" + asset.decode(), timeout=5) as response:
                data = response.read(2 * 1024 * 1024)
                assert len(data) == int(response.headers["Content-Length"])
            expected = (ROOT / "console/dist" / asset.decode().lstrip("/")).read_bytes()
            assert data == expected
            asset_records.append(
                {"path": asset.decode(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            )
        (args.output / "assets.json").write_text(json.dumps(asset_records, indent=2) + "\n")
        try:
            opener.open("http://127.0.0.1:8080/internal/m2/adms", timeout=3)
            raise AssertionError("Private control route is public")
        except urllib.error.HTTPError as error:
            assert error.code == 404
        check("host_loopback_health_assets_and_control_separation")
        check("nonroot_readonly_caps_loopback_ports_and_private_volumes")
        network_probe = """
import json,socket
try:
 s=socket.create_connection(('1.1.1.1',443),timeout=2);s.close();connected=True
except OSError: connected=False
print(json.dumps({'external_tcp':connected}))
"""
        for role in ("app", "learning-worker", "provider-gateway"):
            probe = json.loads(run([*compose, "exec", "-T", role, "python", "-c", network_probe]))
            assert probe["external_tcp"] == (role == "provider-gateway"), (role, probe)
        check("only_gateway_has_external_tcp_egress")
        denied = json.loads(
            run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "app",
                    "python",
                    "-c",
                    "import socket,json\nblocked=[]\nfor family,kind in [(socket.AF_INET,socket.SOCK_DGRAM),(socket.AF_INET6,socket.SOCK_DGRAM),(socket.AF_INET,socket.SOCK_RAW),(socket.AF_PACKET,socket.SOCK_RAW)]:\n try: s=socket.socket(family,kind); s.close(); blocked.append(False)\n except PermissionError: blocked.append(True)\nprint(json.dumps({'denied':all(blocked)}))",
                ]
            )
        )
        assert denied["denied"]
        check("app_syscall_policy_denies_datagram_and_raw_sockets")

        base = "/internal/m2/adms"
        rpc(base, {"name": "forbidden"}, role="worker", expected=403)
        rpc(base, {"name": "forbidden"}, role="gateway", expected=403)
        empty = rpc(base, {"name": "runtime empty"})
        package = read_snapshot(ROOT / "tests/fixtures/v1/reference/tanks.adm")
        tank = rpc(base, {"name": "runtime tanks", "mode": "forward", "snapshot": pack(package)})
        path = base + "/" + tank["id"]
        query = {
            "op": "find_plan",
            "module": "tanks",
            "initial_state": {"left": 0, "right": 0},
            "goal": "tanks.four_litres",
        }
        result = rpc(path + "/compute", {"query": query})
        assert result["result"]["steps"] == 6 and result["result"]["witness_replayed"]
        assert (
            rpc(base + "/" + empty["id"] + "/compute", {"query": {"op": "capabilities"}})["result"]["status"]
            == "succeeded"
        )
        check("authenticated_empty_and_snapshot_instances_compute_locally")

        certificate = build_certificate(
            Instance.restore(package).model,
            "tanks",
            {"left": 0, "right": 0},
            "tanks.four_litres",
            transitions=["tanks.empty_left", "tanks.empty_right", "tanks.fill_left", "tanks.fill_right"],
        )
        proof_body = {"query": {"op": "check_certificate", "certificate": certificate, "backend": "lean"}}
        formal = rpc(path + "/compute", proof_body)["result"]
        assert formal["certificate_status"] == "verified"
        assert formal["checker"]["guarantee"] == "lean_kernel"
        assert formal["correspondence"]["guarantee"] == "exhaustive_finite"
        check("production_linux_lean_and_finite_correspondence")

        run([*compose, "stop", "learning-worker", "provider-gateway"])
        assert rpc(path + "/compute", {"query": query})["result"]["steps"] == 6
        assert rpc(path + "/compute", proof_body)["result"]["certificate_status"] == "verified"
        check("serving_and_lean_work_with_worker_and_gateway_stopped")
        run([*compose, "restart", "app"])
        run([*compose, "up", "-d", "--wait", "--wait-timeout", "60"], timeout=75)
        assert rpc(path) == tank
        assert rpc(base + "/" + empty["id"]) == empty
        assert rpc(path + "/runs/" + result["id"]) == result
        check("instance_identity_policy_mode_and_results_survive_restart")

        # Authored interruption: pause the real compute child, then kill the app
        # container. No implementation test hooks or fake result enter the server.
        watcher_code = """
import json,os,signal,sqlite3,sys,time
from pathlib import Path
deadline=time.monotonic()+8
while time.monotonic()<deadline:
 for p in Path('/proc').glob('[0-9]*/cmdline'):
  try: command=p.read_bytes()
  except OSError: continue
  if b'awm_adm.runtime.compute' in command.split(b'\\0'):
   os.kill(int(p.parent.name),signal.SIGSTOP)
   with sqlite3.connect('file:/var/lib/awm-adm/'+sys.argv[1]+'.db?mode=ro',uri=True) as connection:
    row=connection.execute("SELECT id FROM runs WHERE status='running' ORDER BY rowid DESC LIMIT 1").fetchone()
   print(json.dumps({'run_id':row[0]}),flush=True);sys.exit(0)
 time.sleep(.01)
sys.exit(2)
"""
        watcher = subprocess.Popen(
            [*compose, "exec", "-T", "app", "python", "-c", watcher_code, tank["id"]],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        computing = subprocess.Popen(
            operator,
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        computing.stdin.write(json.dumps({"path": path + "/compute", "body": proof_body}))
        computing.stdin.close()
        stdout, stderr = watcher.communicate(timeout=12)
        assert watcher.returncode == 0, stderr
        interrupted = json.loads(stdout)["run_id"]
        run([*compose, "kill", "-s", "SIGKILL", "app"])
        computing.wait(timeout=10)
        run([*compose, "up", "-d", "--wait", "--wait-timeout", "60"], timeout=75)
        recovered = rpc(path + "/runs/" + interrupted)
        assert recovered["status"] == "interrupted" and recovered["result"] is None
        assert rpc(path + "/compute", {"query": query})["result"]["steps"] == 6
        check("app_sigkill_during_real_compute_fences_result_and_recovers")
        (args.output / "instances.json").write_text(
            json.dumps(
                {"empty": empty, "tanks": tank, "plan_run": result["id"], "interrupted_run": interrupted},
                indent=2,
            )
            + "\n"
        )
        status = "passed"
    except BaseException:
        status = "failed"
        raise
    finally:
        try:
            run([*compose, "logs", "--no-color", "--tail", "100"])
            run([*compose, "stop"])
        finally:
            (args.output / "report.json").write_text(
                json.dumps(
                    {
                        "status": status,
                        "checks": checks,
                        "commands": commands,
                        "live_provider_calls": 0,
                        "volumes_preserved": True,
                    },
                    indent=2,
                )
                + "\n"
            )


if __name__ == "__main__":
    main()
