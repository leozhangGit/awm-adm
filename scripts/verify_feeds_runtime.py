"""feeds isolated Docker acceptance. Authored history and recorded extraction; no live calls."""

import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--override", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8086)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.project.startswith("awm-adm-check-feeds-") or args.port == 8080:
        raise ValueError("Use an isolated feeds project and nonproduction port")
    args.output.mkdir(parents=True, exist_ok=False)
    token = (ROOT / ".local/secrets/owner-token").read_text().strip()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    checks = []

    def api(path, body=None, method=None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{args.port}/api/v1" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            method=method or ("POST" if body is not None else "GET"),
        )
        with opener.open(request, timeout=30) as response:
            return json.load(response)

    def wait(read, predicate):
        end = time.monotonic() + 60
        while time.monotonic() < end:
            value = read()
            if predicate(value):
                return value
            time.sleep(0.2)
        raise AssertionError(value)

    def create(name):
        op = api("/adms", {"idempotency_key": str(uuid4()), "name": name})
        done = wait(
            lambda: api("/operations/" + op["operation_id"]), lambda v: v["status"] in ("succeeded", "failed")
        )
        assert done["status"] == "succeeded", done
        return done["result"]["adm_id"]

    def scope(a, b):
        return {
            "kind": "interval",
            "granularity": "year",
            "effective_from": f"{a}-01-01T00:00:00Z",
            "effective_to": f"{b}-01-01T00:00:00Z",
        }

    policy = json.loads((ROOT / "examples/sources/historical-policy.json").read_text())

    def install(key):
        return api(
            f"/adms/{key}/sources/policy",
            {**policy, "expected_revision": api(f"/adms/{key}")["revision_id"], "expected_generation": 0},
            "PUT",
        )

    def fact(n, a, b):
        return {
            "entity_id": "site",
            "predicate": "site.capacity",
            "value": {"kind": "integer", "value": n},
            "unit": "places",
            "temporal_scope": scope(a, b),
            "assertion_kind": "assertion",
        }

    def append(key, item, content):
        body = {
            "idempotency_key": str(uuid4()),
            "items": [
                {
                    "source_id": "records",
                    "item_id": item,
                    "version_id": "v1",
                    "media_type": "application/json",
                    "content": json.dumps([content]),
                    "origin": "Authored feeds append client",
                }
            ],
        }
        response = api(f"/adms/{key}/sources/batches", body)
        assert api(f"/adms/{key}/sources/batches", body) == response
        return response

    def query(key, year, status="succeeded"):
        request = api(
            f"/adms/{key}/requests",
            {
                "idempotency_key": str(uuid4()),
                "query": {
                    "op": "lookup_fact",
                    "entity_id": "site",
                    "predicate": "site.capacity",
                    "effective_at": f"{year}-01-01T00:00:00Z",
                },
            },
        )
        result = wait(
            lambda: api(f"/adms/{key}/requests/" + request["request_id"]),
            lambda r: r["status"] not in ("received", "evaluating"),
        )
        assert result["status"] == status, result
        return result

    key = create("[feeds trial] Continuous history")
    install(key)
    f = api(
        f"/adms/{key}/feeds",
        {
            "idempotency_key": str(uuid4()),
            "name": "Local history append feed",
            "expected_revision": api(f"/adms/{key}")["revision_id"],
            "expected_source_generation": 1,
            "source_ids": ["records"],
            "enabled": True,
            "publication": "checked_auto",
            "requirements": policy["projection"]["predicates"],
            "budget": {
                "max_items": 4,
                "max_calls": 0,
                "max_input_tokens": 0,
                "max_output_tokens": 0,
                "max_work": 12000000,
            },
        },
    )

    def page():
        return api(f"/adms/{key}/feeds")

    append(key, "initial", fact(10, 2020, 2024))
    wait(page, lambda p: p["feeds"][0]["admitted"] == 1)
    first = query(key, 2021)
    append(key, "later", fact(12, 2024, 2026))
    during = query(key, 2021)
    wait(page, lambda p: p["feeds"][0]["admitted"] == 2)
    second = query(key, 2025)
    checks.append(
        {
            "check": "continuous_append_without_waiting_request_and_local_serving",
            "passed": True,
            "request_ids": [r["request_id"] for r in (first, during, second)],
        }
    )
    info = api(f"/adms/{key}")
    paused = api(
        f"/adms/{key}/feeds/" + f["id"],
        {"expected_generation": f["generation"], "expected_revision": info["revision_id"], "enabled": False},
        "PUT",
    )
    append(key, "unsupported", fact(14, 2026, 2028))
    before = page()
    command = [
        "docker",
        "compose",
        "-p",
        args.project,
        "-f",
        "compose.yaml",
        "-f",
        str(args.override),
        "restart",
        "app",
    ]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=90)
    (args.output / "restart.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0
    for _ in range(120):
        try:
            after = page()
            break
        except (OSError, ValueError):
            time.sleep(0.25)
    else:
        raise AssertionError("App did not return")
    assert after["feeds"][0]["reserved"] == before["feeds"][0]["reserved"]
    assert after["feeds"][0]["admitted"] == 2 and after["feeds"][0]["backlog"] == 1
    api(
        f"/adms/{key}/feeds/" + f["id"],
        {
            "expected_generation": paused["generation"],
            "expected_revision": api(f"/adms/{key}")["revision_id"],
            "enabled": True,
        },
        "PUT",
    )
    wait(page, lambda p: p["feeds"][0]["counts"].get("held") == 1)
    query(key, 2027, "needs_input")
    checks.append(
        {
            "check": "pause_restart_resumes_cursor_no_duplicate_acceptance_outside_coverage_held",
            "passed": True,
        }
    )
    # Recorded extraction traverses the same worker/gateway without network egress.
    other = create("[feeds trial] Recorded extraction")
    install(other)
    content = json.dumps([fact(10, 2020, 2024)])
    c = api(
        "/connections",
        {
            "idempotency_key": str(uuid4()),
            "name": "feeds recorded source fixture",
            "provider": "recorded",
            "model": "authored",
            "enabled": True,
            "purposes": ["extraction"],
            "recorded_responses": [
                {"claims": [{**fact(10, 2020, 2024), "start_byte": 0, "end_byte": len(content.encode())}]}
            ],
        },
    )
    c = wait(lambda: api("/connections/" + c["id"]), lambda v: v["status"] == "ready")
    api(
        f"/adms/{other}/feeds",
        {
            "idempotency_key": str(uuid4()),
            "name": "Recorded bounded extraction",
            "expected_revision": api(f"/adms/{other}")["revision_id"],
            "expected_source_generation": 1,
            "source_ids": ["records"],
            "enabled": True,
            "publication": "checked_auto",
            "requirements": policy["projection"]["predicates"],
            "extractor": "external",
            "allow_external": True,
            "connection_id": c["id"],
            "connection_version": c["version"],
            "budget": {"max_items": 1, "max_calls": 1, "max_work": 3000000},
        },
    )
    append(other, "recorded", fact(10, 2020, 2024))
    recorded = wait(lambda: api(f"/adms/{other}/feeds"), lambda p: p["feeds"][0]["admitted"] == 1)
    query(other, 2021)
    assert recorded["feeds"][0]["reserved"]["calls"] == 1
    assert api("/learning")["remote_calls_enabled"] is False
    checks.append({"check": "recorded_gateway_feed_one_reserved_call", "passed": True})
    report = {
        "project": args.project,
        "port": args.port,
        "live_provider_calls": 0,
        "checks": checks,
        "adm_id": key,
        "recorded_adm_id": other,
        "feeds": page(),
        "recorded_feeds": recorded,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": len(checks), "adm_id": key, "output": str(args.output)}))


if __name__ == "__main__":
    main()
