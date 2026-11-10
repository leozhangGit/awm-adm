"""Release equipment rehearsal against an isolated exported Docker stack; recorded providers only."""

import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument(
        "--override", type=Path, required=True, help="Compose override, relative to package or absolute"
    )
    parser.add_argument("--port", type=int, default=8089)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        not args.project.startswith("awm-adm-check-release-")
        or not 1024 <= args.port <= 65535
        or args.port in (8080, 8081)
    ):
        raise ValueError("Use a dedicated release project and nonproduction port")
    root = args.package.resolve()
    override = (root / args.override).resolve()
    if not override.is_file():
        raise ValueError("Compose override must exist; follow docs/TESTING.md rehearsal setup")
    manifest = json.loads((root / "release-manifest.json").read_text())
    if manifest["profile"] != "awm-adm-source-release/1":
        raise ValueError("A clean exported package is required")
    args.output.mkdir(parents=True, exist_ok=False)
    token = (root / ".local/secrets/owner-token").read_text().strip()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    checks, records = [], {}
    compose = [
        "docker",
        "compose",
        "-p",
        args.project,
        "-f",
        "compose.yaml",
        "-f",
        str(override),
    ]

    def fixture(name):
        return json.loads((root / "examples/equipment" / name).read_text())

    def api(path, body=None, method=None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{args.port}/api/v1" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            method=method or ("POST" if body is not None else "GET"),
        )
        with opener.open(request, timeout=30) as response:
            return json.load(response)

    def command(*arguments):
        result = subprocess.run([*compose, *arguments], cwd=root, text=True, capture_output=True, timeout=90)
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout

    def wait(read, statuses=("succeeded",)):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            value = read()
            if value["status"] in statuses:
                return value
            if value["status"] in ("failed", "stopped", "cancelled", "rejected", "inconclusive"):
                raise AssertionError(value)
            time.sleep(0.15)
        raise AssertionError(value)

    def create(name, snapshot=None):
        op = api(
            "/adms",
            {"idempotency_key": str(uuid4()), "name": name, **({"snapshot": snapshot} if snapshot else {})},
        )
        return wait(lambda: api("/operations/" + op["operation_id"]))["result"]["adm_id"]

    def query(key, body, statuses=("succeeded",)):
        request = api(f"/adms/{key}/requests", {"idempotency_key": str(uuid4()), "query": body})
        return wait(lambda: api(f"/adms/{key}/requests/{request['request_id']}"), statuses)

    def recorded(purpose, response):
        c = api(
            "/connections",
            {
                "idempotency_key": str(uuid4()),
                "name": "[release recorded] " + purpose,
                "provider": "recorded",
                "model": "authored-equipment",
                "enabled": True,
                "purposes": [purpose],
                "recorded_responses": [response],
            },
        )
        return wait(lambda: api("/connections/" + c["id"]), ("ready",))

    try:
        assert api("/learning")["remote_calls_enabled"] is False
        assert not api("/adms")["items"] and not api("/connections")["items"]
        records["lean"] = command("exec", "-T", "app", "/opt/lean/bin/lean", "--version").strip()
        assert "4.19.0" in records["lean"]
        key = create("[release recorded] Equipment learned from empty")
        base = f"/adms/{key}"

        def info():
            return api(base)

        api(
            base + "/requirements",
            {"expected_epoch": info()["policy_epoch"], "policy": fixture("requirements.json")},
            "PUT",
        )
        expected = fixture("expected.json")
        pending = query(key, expected["translation_query"], ("needs_input",))
        c = recorded("acquisition", fixture("recorded-acquisition.json"))
        ep = api(
            base + "/episodes",
            {
                "idempotency_key": str(uuid4()),
                "expected_revision": info()["revision_id"],
                "connection_id": c["id"],
                "connection_version": c["version"],
                "task": fixture("task.json"),
                "request_ids": [pending["request_id"]],
            },
        )
        query(key, {"op": "capabilities"})
        held = wait(lambda: api(base + "/episodes/" + ep["id"]), ("awaiting_review",))
        assert query(key, expected["translation_query"], ("needs_input",))["status"] == "needs_input"
        api(
            base + f"/candidates/{held['receipts'][-1]['id']}/review",
            {"expected_revision": info()["revision_id"], "approve": True},
        )
        wait(lambda: api(base + "/episodes/" + ep["id"]), ("accepted",))
        for case in expected["truth_table"]:
            expression = {
                "op": "call",
                "function": "equipment.can_borrow",
                "args": {k: {"op": "literal", "value": case[k]} for k in ("borrowed", "available")},
            }
            assert (
                query(key, {"op": "evaluate", "module": "equipment", "expression": expression})["result"][
                    "value"
                ]["value"]
                is case["expected"]
            )
        checks.append(
            "empty_start_independent_requirements_recorded_acquisition_nine_cases_concurrent_local_serving"
        )
        conv = api(
            base + "/interpretation-sessions",
            {"idempotency_key": str(uuid4()), "title": "Recorded owner journey"},
        )
        translator = recorded(
            "interpretation",
            {
                "status": "ready",
                "command": expected["local_command"],
                "assumptions": [],
                "clarification": None,
            },
        )
        turn = api(
            base + "/interpretations",
            {
                "idempotency_key": str(uuid4()),
                "expected_revision": info()["revision_id"],
                "conversation_id": conv["id"],
                "utterance": expected["translation_utterance"],
                "translator": "external",
                "connection_id": translator["id"],
                "connection_version": translator["version"],
                "disclose_catalog": True,
            },
        )
        ready = wait(lambda: api(base + "/interpretations/" + turn["id"]), ("ready",))
        assert ready["draft"]["query"] == expected["translation_query"]
        request = api(
            base + f"/interpretations/{turn['id']}/execute",
            {
                "idempotency_key": str(uuid4()),
                "expected_revision": ready["revision_id"],
                "expected_catalog_digest": ready["draft"]["catalog_digest"],
            },
        )
        wait(lambda: api(base + "/requests/" + request["request_id"]))
        revision = info()["revision_id"]
        teaching = api(
            base + f"/interpretation-sessions/{conv['id']}/teach",
            {
                "idempotency_key": str(uuid4()),
                "expected_revision": revision,
                "text": "Synthetic register: camera-kit capacity was two items in 2025.",
            },
        )
        assert teaching["status"] == "draft" and info()["revision_id"] == revision
        checks.append("recorded_translation_preview_explicit_local_execution_teach_remains_draft")
        policy = fixture("source-policy.json")
        api(
            base + "/sources/policy",
            {"expected_revision": revision, "expected_generation": 0, **policy},
            "PUT",
        )
        feed = api(
            base + "/feeds",
            {
                "idempotency_key": str(uuid4()),
                "name": "Local equipment records",
                "expected_revision": info()["revision_id"],
                "expected_source_generation": 1,
                "source_ids": ["equipment-register"],
                "enabled": True,
                "publication": "checked_auto",
                "requirements": policy["projection"]["predicates"],
                "budget": {
                    "max_items": 2,
                    "max_calls": 0,
                    "max_input_tokens": 0,
                    "max_output_tokens": 0,
                    "max_work": 12000000,
                },
            },
        )

        def source(name, item=None, version="v1", supersedes=None):
            src = {
                "source_id": "equipment-register",
                "item_id": item or str(uuid4()),
                "version_id": version,
                "media_type": "application/json",
                "origin": "Synthetic release equipment fixture",
                "content": json.dumps(fixture(name)),
                "supersedes_version": supersedes,
            }
            api(base + "/sources/batches", {"idempotency_key": str(uuid4()), "items": [src]})
            return src

        def lookup(year, statuses=("succeeded",)):
            return query(
                key,
                {
                    "op": "lookup_fact",
                    "entity_id": "camera-kit",
                    "predicate": "equipment.capacity",
                    "effective_at": f"{year}-06-01T00:00:00Z",
                },
                statuses,
            )

        source("history-2026.json")
        source("history-2025.json")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if sum(i["status"] == "accepted" for i in api(base + "/feeds")["items"]) == 2:
                break
            time.sleep(0.2)
        else:
            raise AssertionError("Feed did not accept both finite facts")
        f = api(base + "/feeds")["feeds"][0]
        api(
            base + "/feeds/" + feed["id"],
            {
                "expected_generation": f["generation"],
                "expected_revision": info()["revision_id"],
                "enabled": False,
            },
            "PUT",
        )
        assert lookup(2025)["result"]["value"]["value"] == 2
        assert lookup(2026)["result"]["value"]["value"] == 1
        lookup(2027, ("needs_input",))

        def project(src):
            job = api(
                base + "/sources/jobs",
                {
                    "idempotency_key": str(uuid4()),
                    "expected_revision": info()["revision_id"],
                    "expected_generation": 1,
                    **{k: src[k] for k in ("source_id", "item_id", "version_id")},
                },
            )
            extracted = wait(lambda: api(base + "/sources/history/jobs/" + job["id"]), ("extracted",))
            ep = api(
                base + "/sources/episodes",
                {
                    "idempotency_key": str(uuid4()),
                    "expected_revision": info()["revision_id"],
                    "expected_generation": 1,
                    "claim_ids": [c["claim"]["claim_id"] for c in extracted["result"]["claims"]],
                },
            )

            def read():
                return api(base + "/sources/history/episodes/" + ep["id"])

            wait(read, ("awaiting_review",))
            api(
                base + f"/sources/episodes/{ep['id']}/review",
                {"expected_revision": info()["revision_id"], "approve": True},
            )
            return wait(read, ("accepted", "rejected"))

        conflict = source("history-2026-conflict.json")
        assert project(conflict)["status"] == "rejected"
        api(base + "/settings", {"expected_epoch": info()["policy_epoch"], "mode": "forward"}, "PATCH")
        assert lookup(2026)["result"]["value"]["value"] == 1
        assert project(conflict)["status"] == "accepted"
        historical = lookup(2026)
        correction = source("history-2026-correction.json", conflict["item_id"], "v2", "v1")
        lookup(2026, ("needs_input",))
        assert api(base + "/requests/" + historical["request_id"])["result"] == historical["result"]
        assert project(correction)["status"] == "accepted"
        assert lookup(2026)["result"]["value"]["value"] == 1
        checks.append("local_feed_history_gap_pause_backward_forward_correction_retained_results")
        op = api(base + "/snapshot-exports", {"idempotency_key": str(uuid4())})
        snapshot = wait(lambda: api("/operations/" + op["operation_id"]))["result"]["snapshot"]
        clone = create("[release recorded] Independent equipment clone", snapshot)
        assert clone != key
        query(clone, expected["translation_query"])
        assert not api(f"/adms/{clone}/feeds")["feeds"]
        command("stop", "provider-gateway")
        try:
            query(key, expected["translation_query"])
            assert lookup(2025)["result"]["value"]["value"] == 2
        finally:
            command("up", "-d", "--no-build", "--wait", "--wait-timeout", "60", "provider-gateway")
        before = info()
        command("restart", "app")
        command("up", "-d", "--no-build", "--wait", "--wait-timeout", "60")
        assert info()["revision_id"] == before["revision_id"]
        assert lookup(2026)["result"]["value"]["value"] == 1
        checks.append("independent_snapshot_clone_provider_stopped_local_serving_restart")
        assert api("/learning")["usage"]["calls"] == 2
        assert all(c["provider"] == "recorded" for c in api("/connections")["items"])
        records.update(
            adm_id=key,
            clone_id=clone,
            feed_id=feed["id"],
            state=info(),
            usage=api("/learning")["usage"],
            connections=api("/connections")["items"],
        )
        status = "passed"
    except Exception:
        (args.output / "report.json").write_text(
            json.dumps({"status": "failed", "checks": checks, "records": records, "live_calls": 0}, indent=2)
            + "\n"
        )
        raise
    (args.output / "report.json").write_text(
        json.dumps(
            {
                "status": status,
                "checks": checks,
                "records": records,
                "live_calls": 0,
                "scope": "Automated recorded-provider Docker rehearsal, not joint owner acceptance",
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps({"status": status, "checks": len(checks), "live_calls": 0, "adm_id": key}))


if __name__ == "__main__":
    main()
