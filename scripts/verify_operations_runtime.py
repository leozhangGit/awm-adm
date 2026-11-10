"""Isolated operations sustained serving/intake and operational fault checks. No account calls."""

import argparse
import json
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--override", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8087)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        not args.project.startswith("awm-adm-check-operations-")
        or args.port == 8080
        or not 60 <= args.seconds <= 300
    ):
        raise ValueError("Use an isolated operations project, nonproduction port and bounded duration")
    args.output.mkdir(parents=True, exist_ok=False)
    token = (ROOT / ".local/secrets/owner-token").read_text().strip()
    compose = ["docker", "compose", "-p", args.project, "-f", "compose.yaml", "-f", str(args.override)]

    def command(arguments, timeout=90):
        result = subprocess.run(arguments, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise AssertionError(
                {"command": arguments[:4], "exit": result.returncode, "stderr": result.stderr[-1000:]}
            )
        return result.stdout

    def api(path, body=None, method=None, prefix="/api/v1"):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(
            f"http://127.0.0.1:{args.port}" + prefix + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            method=method or ("POST" if body is not None else "GET"),
        )
        with opener.open(request, timeout=30) as response:
            return json.load(response)

    def wait(read, predicate, seconds=60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = read()
            if predicate(result):
                return result
            time.sleep(0.05)
        raise AssertionError(result)

    def create(name, snapshot=None):
        value = {"idempotency_key": str(uuid4()), "name": name}
        if snapshot:
            value["snapshot"] = snapshot
        op = api("/adms", value)
        done = wait(
            lambda: api("/operations/" + op["operation_id"]), lambda v: v["status"] in ("succeeded", "failed")
        )
        assert done["status"] == "succeeded"
        return done["result"]["adm_id"]

    from awm_adm.engine import read_snapshot
    from awm_adm.runtime.protocol import pack

    tanks = create(
        "[operations trial] Sustained local plans",
        pack(read_snapshot(ROOT / "tests/fixtures/v1/reference/tanks.adm")),
    )
    history = create("[operations trial] Sustained history")
    policy = json.loads((ROOT / "examples/sources/historical-policy.json").read_text())
    policy["projection"]["cells"] = [
        {
            "kind": "interval",
            "granularity": "year",
            "effective_from": f"{year}-01-01T00:00:00Z",
            "effective_to": f"{year + 1}-01-01T00:00:00Z",
        }
        for year in range(2000, 2021)
    ]
    policy["projection"]["predicates"][0]["maximum"] = 40
    policy["sources"][0]["source_id"] = "operations-fixture"
    api(
        f"/adms/{history}/sources/policy",
        {**policy, "expected_revision": api(f"/adms/{history}")["revision_id"], "expected_generation": 0},
        "PUT",
    )
    api(
        f"/adms/{history}/feeds",
        {
            "idempotency_key": str(uuid4()),
            "name": "Bounded operations fixture feed",
            "expected_revision": api(f"/adms/{history}")["revision_id"],
            "expected_source_generation": 1,
            "source_ids": ["operations-fixture"],
            "enabled": True,
            "publication": "checked_auto",
            "requirements": policy["projection"]["predicates"],
            "budget": {
                "max_items": 21,
                "max_calls": 0,
                "max_input_tokens": 0,
                "max_output_tokens": 0,
                "max_work": 63000000,
            },
        },
    )

    def append(index):
        year = 2000 + index
        fact = {
            "entity_id": "site",
            "predicate": "site.capacity",
            "value": {"kind": "integer", "value": 10 + index},
            "unit": "places",
            "assertion_kind": "assertion",
            "temporal_scope": {
                "kind": "interval",
                "granularity": "year",
                "effective_from": f"{year}-01-01T00:00:00Z",
                "effective_to": f"{year + 1}-01-01T00:00:00Z",
            },
        }
        body = {
            "idempotency_key": "operations-source-" + str(index),
            "items": [
                {
                    "source_id": "operations-fixture",
                    "item_id": str(index),
                    "version_id": "v1",
                    "media_type": "application/json",
                    "content": json.dumps([fact]),
                    "origin": "Authored operations fixture",
                }
            ],
        }
        result = api(f"/adms/{history}/sources/batches", body)
        assert api(f"/adms/{history}/sources/batches", body) == result
        return result

    append(0)
    wait(lambda: api(f"/adms/{history}/feeds"), lambda p: p["feeds"][0]["admitted"] == 1)
    plan = {
        "op": "find_plan",
        "module": "tanks",
        "initial_state": {"left": 0, "right": 0},
        "goal": "tanks.four_litres",
    }
    fact_query = {
        "op": "lookup_fact",
        "entity_id": "site",
        "predicate": "site.capacity",
        "effective_at": "2000-06-01T00:00:00Z",
    }

    def query(key, body):
        start = time.monotonic()
        request = api(f"/adms/{key}/requests", {"idempotency_key": str(uuid4()), "query": body})
        done = wait(
            lambda: api(f"/adms/{key}/requests/" + request["request_id"]),
            lambda r: r["status"] not in ("received", "evaluating"),
        )
        assert done["status"] == "succeeded", done
        if key == tanks:
            assert done["result"]["value"]["steps"] == 6
        return {
            "request_id": done["request_id"],
            "seconds": time.monotonic() - start,
            "status": done["status"],
        }

    start_diag = api("/operations/diagnostics")
    started = time.monotonic()

    def serving(key, body):
        samples = []
        while time.monotonic() - started < args.seconds:
            samples.append(query(key, body))
            time.sleep(0.5)
        return samples

    def intake():
        times = []
        for index in range(1, 21):
            target = started + (index - 1) * args.seconds / 20
            time.sleep(max(0, target - time.monotonic()))
            append(index)
            times.append(time.monotonic() - started)
        return times

    def monitor():
        observations = []
        while time.monotonic() - started < args.seconds:
            raw = command(
                [
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{json .}}",
                    *command([*compose, "ps", "-q"]).split(),
                ],
                timeout=15,
            )
            observations.append(
                {
                    "elapsed_seconds": time.monotonic() - started,
                    "containers": [
                        {k: value[k] for k in ("Name", "CPUPerc", "MemUsage", "MemPerc", "PIDs")}
                        for value in (json.loads(line) for line in raw.splitlines())
                    ],
                    "feed": api(f"/adms/{history}/feeds")["feeds"][0]["counts"],
                }
            )
            time.sleep(3)
        return observations

    with ThreadPoolExecutor(max_workers=4) as pool:
        monitoring = pool.submit(monitor)
        plans = pool.submit(serving, tanks, plan)
        facts = pool.submit(serving, history, fact_query)
        ingestion = pool.submit(intake)
        samples = plans.result() + facts.result()
        intake_times = ingestion.result()
        resource_samples = monitoring.result()
    feed = wait(lambda: api(f"/adms/{history}/feeds"), lambda p: p["feeds"][0]["admitted"] == 21)
    finish_diag = api("/operations/diagnostics")
    elapsed = time.monotonic() - started
    values = sorted(r["seconds"] for r in samples)
    workload = {
        "duration_seconds": elapsed,
        "requested_seconds": args.seconds,
        "clients": 2,
        "pacing_seconds_after_result": 0.5,
        "source_versions": 21,
        "duplicate_intake_retries": 21,
        "admitted": feed["feeds"][0]["admitted"],
        "requests": len(samples),
        "result_latency_seconds": {
            "median": statistics.median(values),
            "p95": values[int(0.95 * (len(values) - 1))],
            "max": max(values),
        },
        "intake_elapsed_seconds": intake_times,
        "request_samples": samples,
        "resource_samples": resource_samples,
        "storage_growth_bytes": finish_diag["storage"]["bytes"] - start_diag["storage"]["bytes"],
        "before": start_diag,
        "after": finish_diag,
    }
    (args.output / "workload.json").write_text(json.dumps(workload, indent=2) + "\n")
    checks = ["sustained_local_serving_during_20_new_source_admissions"]
    command([*compose, "stop", "learning-worker", "provider-gateway"])
    time.sleep(16)
    readiness = api("/health/ready", prefix="")
    assert readiness["components"]["local_serving"]
    assert not readiness["components"]["worker"] and not readiness["components"]["gateway"]
    query(tanks, plan)
    query(history, fact_query)
    checks.append("provider_unavailable_and_missed_heartbeat_preserve_local_serving")

    watcher = r"""
import json,os,signal,sqlite3,sys,time
from pathlib import Path
end=time.monotonic()+12
while time.monotonic()<end:
 for p in Path('/proc').glob('[0-9]*/cmdline'):
  try: raw=p.read_bytes()
  except OSError: continue
  if b'awm_adm.runtime.compute' in raw.split(b'\0'):
   os.kill(int(p.parent.name),signal.SIGSTOP)
   with sqlite3.connect('file:/var/lib/awm-adm/'+sys.argv[1]+'.db?mode=ro',uri=True) as db:
    row=db.execute("SELECT id FROM requests WHERE status='evaluating' ORDER BY seq DESC LIMIT 1").fetchone()
   if row: print(json.dumps({'request_id':row[0]}),flush=True);sys.exit(0)
 time.sleep(.001)
sys.exit(2)
"""
    before = api(f"/adms/{tanks}")
    watching = subprocess.Popen(
        [*compose, "exec", "-T", "app", "python", "-c", watcher, tanks],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.2)
    submitted = api(
        f"/adms/{tanks}/requests", {"idempotency_key": "operations-interrupted-request", "query": plan}
    )
    observed, error = watching.communicate(timeout=20)
    assert watching.returncode == 0, error
    assert json.loads(observed)["request_id"] == submitted["request_id"]
    command([*compose, "kill", "-s", "SIGKILL", "app"])
    command([*compose, "up", "-d", "--wait", "--wait-timeout", "60"])
    recovered = api(f"/adms/{tanks}/requests/" + submitted["request_id"])
    assert recovered["status"] == "inconclusive" and recovered["result"] is None
    assert api(f"/adms/{tanks}") == before
    query(tanks, plan)
    checks.append("real_app_sigkill_during_paused_compute_fences_stale_publication")
    ids = command([*compose, "ps", "-q"]).split()
    inspected = json.loads(command(["docker", "inspect", *ids]))
    roles = {c["Config"]["Labels"]["com.docker.compose.service"]: c for c in inspected}
    network = []
    for role, container in roles.items():
        assert container["Config"]["User"] == "10001:10001" and container["HostConfig"]["ReadonlyRootfs"]
        assert container["HostConfig"]["CapDrop"] == ["ALL"]
        probe = command(
            [
                *compose,
                "exec",
                "-T",
                role,
                "python",
                "-c",
                "import socket,json\ntry:\n s=socket.create_connection(('1.1.1.1',443),timeout=2);s.close();v=True\nexcept OSError:v=False\nprint(json.dumps({'external_tcp':v}))",
            ]
        )
        value = json.loads(probe)
        assert value["external_tcp"] == (role == "provider-gateway")
        network.append(
            {
                "role": role,
                **value,
                "networks": list(container["NetworkSettings"]["Networks"]),
                "ports": container["HostConfig"]["PortBindings"],
            }
        )
    udp = command(
        [
            *compose,
            "exec",
            "-T",
            "app",
            "python",
            "-c",
            "import socket,json\na=[]\nfor kind in (socket.SOCK_DGRAM,socket.SOCK_RAW):\n try:s=socket.socket(socket.AF_INET,kind);s.close();a.append(False)\n except PermissionError:a.append(True)\nprint(json.dumps(a))",
        ]
    )
    assert all(json.loads(udp))
    checks.append("actual_egress_permissions_and_socket_denial")
    environment = {
        "docker": json.loads(command(["docker", "info", "--format", "{{json .}}"])),
        "images": json.loads(command(["docker", "image", "inspect", *[c["Image"] for c in inspected]])),
    }
    # Keep only bounded hardware/image identity fields, not host paths or environment values.
    hardware = {
        k: environment["docker"][k]
        for k in ("Architecture", "OSType", "OperatingSystem", "NCPU", "MemTotal", "ServerVersion")
    }
    images = [{k: i[k] for k in ("Id", "Architecture", "Os")} for i in environment["images"]]
    report = {
        "status": "passed",
        "live_provider_calls": 0,
        "checks": checks,
        "hardware": hardware,
        "images": images,
        "network": network,
        "instances": {"plans": tanks, "history": history},
        "interrupted_request": submitted["request_id"],
        "workload_summary": {
            k: v
            for k, v in workload.items()
            if k not in ("before", "after", "request_samples", "intake_elapsed_seconds", "resource_samples")
        },
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["workload_summary"]), flush=True)


if __name__ == "__main__":
    main()
