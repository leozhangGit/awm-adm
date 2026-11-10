"""Bounded offline learning HTTP/container trial against an already-running dedicated stack."""

import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

from awm_adm.engine import Instance
from awm_adm.runtime.protocol import pack

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--override", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.project.startswith("awm-adm-check-learning-") or args.port == 8080:
        raise ValueError("Use a dedicated learning project and verification port")
    args.output.mkdir(parents=True, exist_ok=False)
    compose = ["docker", "compose", "-p", args.project, "-f", "compose.yaml", "-f", str(args.override)]
    owner = (ROOT / ".local/secrets/owner-token").read_text().strip()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    checks, commands = [], []

    def command(arguments, timeout=90):
        result = subprocess.run(
            [*compose, *arguments], cwd=ROOT, text=True, capture_output=True, timeout=timeout
        )
        commands.append(
            {
                "arguments": arguments,
                "exit_code": result.returncode,
                "output": result.stdout,
                "stderr": result.stderr,
            }
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    def api(path, body=None, method=None):
        raw = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"http://127.0.0.1:{args.port}/api/v1" + path,
            data=raw,
            headers={"Authorization": "Bearer " + owner, "Content-Type": "application/json"},
            method=method or ("POST" if raw is not None else "GET"),
        )
        with opener.open(request, timeout=20) as response:
            return json.load(response)

    def wait(path, status):
        end = time.monotonic() + 45
        while time.monotonic() < end:
            result = api(path)
            if result["status"] in status:
                return result
            time.sleep(0.1)
        raise AssertionError((path, result))

    def request(key, query, *, statuses=("succeeded",)):
        row = api(f"/adms/{key}/requests", {"idempotency_key": str(uuid4()), "query": query})
        return wait(f"/adms/{key}/requests/{row['request_id']}", statuses)

    try:
        settings = api("/learning")
        assert settings["remote_calls_enabled"] is False
        assert all(c["provider"] == "recorded" or not c["enabled"] for c in api("/connections")["items"])
        fixture = json.loads((ROOT / "console/public/examples/learning-capacity.json").read_text())
        bad = json.loads(json.dumps(fixture["replies"][0]))
        bad["result"]["definitions"]["site.capacity"]["body"]["value"] = 12
        c = api(
            "/connections",
            {
                "idempotency_key": str(uuid4()),
                "name": "[learning HTTP] Authored bad then good",
                "provider": "recorded",
                "model": "authored-capacity",
                "enabled": True,
                "recorded_responses": [bad, *fixture["replies"]],
            },
        )
        wait("/connections/" + c["id"], ("ready",))
        policy = {
            "profile": "adm-conformance/0.1",
            "contracts": [
                {
                    "contract_id": "owner-capacity-ten",
                    "origin": "Authored learning fixture requirement",
                    "required_symbols": ["site.capacity"],
                    "checks": [
                        {
                            "id": "capacity",
                            "kind": "value",
                            "params": {},
                            "expression": {"op": "call", "function": "site.capacity", "args": {}},
                            "expected": {"op": "literal", "value": 10},
                        }
                    ],
                }
            ],
        }
        # Construct an independent policy snapshot locally; provider replies cannot edit it.
        snapshot = pack(Instance(policy=policy).export_snapshot())
        operation = api(
            "/adms",
            {
                "idempotency_key": str(uuid4()),
                "name": "[learning HTTP] Independent requirements",
                "snapshot": snapshot,
            },
        )
        key = wait("/operations/" + operation["operation_id"], ("succeeded",))["result"]["adm_id"]
        query = {
            "op": "evaluate",
            "expression": {"op": "call", "function": "site.capacity", "args": {}},
            "module": "site",
        }
        pending = request(key, query, statuses=("needs_input",))
        caps = settings["episode_caps"]
        ep = api(
            f"/adms/{key}/episodes",
            {
                "idempotency_key": str(uuid4()),
                "expected_revision": api("/adms/" + key)["revision_id"],
                "connection_id": c["id"],
                "connection_version": 1,
                "task": fixture["task"],
                "publication": "checked_auto",
                "request_ids": [pending["request_id"]],
                "limits": caps,
                "call_limits": settings["call_caps"],
            },
        )
        concurrent = request(key, {"op": "capabilities"})
        done = wait(f"/adms/{key}/episodes/{ep['id']}", ("accepted", "stopped"))
        assert done["status"] == "accepted", done
        assert [r["status"] for r in done["receipts"]] == ["rejected", "accepted"]
        result = wait(f"/adms/{key}/requests/{pending['request_id']}", ("succeeded",))
        assert result["result"]["value"]["value"] == 10 and len(result["attempts"]) == 2
        checks.append(
            {
                "name": "recorded_repair_with_independent_requirements_and_concurrent_serving",
                "passed": True,
                "episode": done,
                "request": result,
                "concurrent_request": concurrent,
            }
        )
        command(["stop", "learning-worker", "provider-gateway"])
        offline = request(key, query)
        assert offline["result"]["value"]["value"] == 10
        checks.append({"name": "local_serving_during_provider_outage", "passed": True, "request": offline})
        command(["up", "-d", "--no-build", "--wait", "--wait-timeout", "60", "provider-gateway"])
        # Worker remains stopped. Authorize one lease without sending a provider call,
        # then terminate the app to exercise the conservative uncertainty boundary.
        c2 = api(
            "/connections",
            {
                "idempotency_key": str(uuid4()),
                "name": "[learning HTTP] Interrupted dispatch",
                "provider": "recorded",
                "model": "authored-capacity",
                "enabled": True,
                "recorded_responses": fixture["replies"],
            },
        )
        wait("/connections/" + c2["id"], ("ready",))
        ep2 = api(
            f"/adms/{key}/episodes",
            {
                "idempotency_key": str(uuid4()),
                "expected_revision": api("/adms/" + key)["revision_id"],
                "connection_id": c2["id"],
                "connection_version": 1,
                "task": fixture["task"],
            },
        )
        wait(f"/adms/{key}/episodes/{ep2['id']}", ("acquiring",))
        code = "from awm_adm.runtime.component import exchange; from awm_adm.runtime.http import secret; import json; job=exchange('http://app:8081/internal/m5/claim',secret('/run/secrets/worker-token'),{})['job']; assert job; body=exchange('http://app:8081/internal/m5/authorize',secret('/run/secrets/gateway-token'),{'grant_id':job['grant_id'],'lease':job['lease']}); print(json.dumps({'grant_id':body['id']}))"
        grant = json.loads(command(["exec", "-T", "provider-gateway", "python", "-c", code]))["grant_id"]
        before = api("/dispatches/" + grant)
        command(["kill", "-s", "SIGKILL", "app"])
        command(["up", "-d", "--no-build", "--wait", "--wait-timeout", "60", "app"])
        after = api("/dispatches/" + grant)
        assert after["status"] == "outcome_unknown" and after["unresolved"]
        assert all(after[k] == before[k] for k in ("calls", "input_tokens", "output_tokens"))
        assert api(f"/adms/{key}/episodes/{ep2['id']}")["status"] == "stopped"
        command(
            [
                "up",
                "-d",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "60",
                "learning-worker",
                "provider-gateway",
            ]
        )
        assert request(key, query)["result"]["value"]["value"] == 10
        checks.append(
            {
                "name": "interrupted_authorized_dispatch_never_repeated_or_refunded",
                "passed": True,
                "before": before,
                "after": after,
                "scope": "Authored fault: app authorized the dispatch; no provider request was sent.",
            }
        )
        exported = api(f"/adms/{key}/snapshot-exports", {"idempotency_key": str(uuid4())})
        snapshot = wait("/operations/" + exported["operation_id"], ("succeeded",))["result"]["snapshot"]
        restored = api(
            "/adms",
            {
                "idempotency_key": str(uuid4()),
                "name": "[learning HTTP] Independent restored model",
                "snapshot": snapshot,
            },
        )
        other = wait("/operations/" + restored["operation_id"], ("succeeded",))["result"]["adm_id"]
        assert request(other, query)["result"]["value"]["value"] == 10
        checks.append(
            {
                "name": "learned_snapshot_restores_independently",
                "passed": True,
                "source": key,
                "restored": other,
            }
        )
        status = "passed"
    except Exception:
        status = "failed"
        raise
    finally:
        (args.output / "report.json").write_text(
            json.dumps(
                {
                    "status": status,
                    "project": args.project,
                    "port": args.port,
                    "live_provider_calls": 0,
                    "checks": checks,
                    "commands": commands,
                },
                indent=2,
            )
            + "\n"
        )
    print(json.dumps({"status": status, "checks": len(checks), "live_provider_calls": 0}))


if __name__ == "__main__":
    main()
