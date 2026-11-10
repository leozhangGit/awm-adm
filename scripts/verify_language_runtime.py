"""Offline language HTTP trial in dedicated containers; recorded interpretation only."""

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--override", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8084)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.project.startswith("awm-adm-check-language-") or args.port == 8080:
        raise ValueError("Use dedicated language volumes and a nonproduction port")
    args.output.mkdir(parents=True, exist_ok=False)
    owner = (ROOT / ".local/secrets/owner-token").read_text().strip()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    checks, commands = [], []
    fixtures = {}
    status = "failed"

    def api(path, body=None, method=None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{args.port}/api/v1" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + owner, "Content-Type": "application/json"},
            method=method or ("POST" if body is not None else "GET"),
        )
        with opener.open(request, timeout=30) as response:
            return json.load(response)

    def command(arguments):
        run = subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                args.project,
                "-f",
                "compose.yaml",
                "-f",
                str(args.override),
                *arguments,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=90,
        )
        commands.append(
            {"arguments": arguments, "exit_code": run.returncode, "output": run.stdout, "stderr": run.stderr}
        )
        assert run.returncode == 0, run.stderr

    def wait(path, statuses):
        end = time.monotonic() + 45
        while time.monotonic() < end:
            value = api(path)
            if value["status"] in statuses:
                return value
            time.sleep(0.15)
        raise AssertionError((path, value))

    def interpret(key, conv, utterance, **extra):
        turn = api(
            f"/adms/{key}/interpretations",
            {
                "idempotency_key": str(uuid4()),
                "expected_revision": api(f"/adms/{key}")["revision_id"],
                "conversation_id": conv,
                "utterance": utterance,
                **extra,
            },
        )
        return wait(
            f"/adms/{key}/interpretations/{turn['id']}",
            ("ready", "needs_clarification", "unsupported", "needs_learning", "failed"),
        )

    def execute(key, turn):
        body = {
            "idempotency_key": "execute:" + turn["id"],
            "expected_revision": turn["revision_id"],
            "expected_catalog_digest": turn["draft"]["catalog_digest"],
        }
        path = f"/adms/{key}/interpretations/{turn['id']}/execute"
        req = api(path, body)
        assert api(path, body)["request_id"] == req["request_id"]
        return wait(f"/adms/{key}/requests/{req['request_id']}", ("succeeded",))

    def connection(reply, name):
        value = api(
            "/connections",
            {
                "idempotency_key": str(uuid4()),
                "name": name,
                "provider": "recorded",
                "model": "authored-language",
                "enabled": True,
                "purposes": ["interpretation"],
                "recorded_responses": [reply],
            },
        )
        return wait("/connections/" + value["id"], ("ready",))

    try:
        assert not api("/learning")["remote_calls_enabled"]
        assert not any(c["enabled"] and c["provider"] != "recorded" for c in api("/connections")["items"])
        for name in ("tanks", "access"):
            created = api(
                "/adms",
                {
                    "idempotency_key": str(uuid4()),
                    "name": "[language HTTP] " + name,
                    "snapshot": json.loads(
                        (ROOT / f"console/public/examples/{name}.snapshot.json").read_text()
                    ),
                },
            )
            key = wait("/operations/" + created["operation_id"], ("succeeded",))["result"]["adm_id"]
            conv = api(
                f"/adms/{key}/interpretation-sessions",
                {"idempotency_key": str(uuid4()), "title": "Authored language trial"},
            )["id"]
            fixtures[name] = {"adm": key, "conversation": conv}
        command(["stop", "learning-worker", "provider-gateway"])
        tank, access = fixtures["tanks"], fixtures["access"]
        phrase = 'plan tanks to tanks.four_litres from {"left":0,"right":0}'
        plan = interpret(tank["adm"], tank["conversation"], phrase)
        assert plan["status"] == "ready"
        assert not api(f"/adms/{tank['adm']}/requests")["items"]
        result = execute(tank["adm"], plan)
        assert result["result"]["value"]["steps"] == 6
        access_turn = interpret(
            access["adm"], access["conversation"], 'evaluate access.open with {"actor":"alice"}'
        )
        assert execute(access["adm"], access_turn)["result"]["value"]["value"] == {
            "tag": "open",
            "value": "alice",
        }
        checks.append(
            {
                "name": "two_catalogs_offline_confirmed_local_answers",
                "passed": True,
                "plan": result,
                "preview": plan["draft"],
            }
        )
        unclear = interpret(tank["adm"], tank["conversation"], "plan tanks to tanks.four_litres")
        assert unclear["status"] == "needs_clarification"
        denied = interpret(tank["adm"], tank["conversation"], "switch to forward mode")
        assert denied["status"] == "unsupported" and api(f"/adms/{tank['adm']}")["mode"] == "backward"
        stale = interpret(tank["adm"], tank["conversation"], "capabilities")
        api(
            f"/adms/{tank['adm']}/language/vocabulary",
            {"expected_revision": stale["revision_id"], "expected_generation": 0, "vocabulary": {}},
            "PUT",
        )
        try:
            execute(tank["adm"], stale)
            raise AssertionError("stale confirmation accepted")
        except urllib.error.HTTPError as error:
            assert error.code == 409
        updated = api(
            f"/adms/{tank['adm']}/interpretations/{stale['id']}/revalidate",
            {"idempotency_key": str(uuid4()), "expected_revision": stale["revision_id"]},
        )
        updated = wait(f"/adms/{tank['adm']}/interpretations/{updated['id']}", ("ready",))
        execute(tank["adm"], updated)
        checks.append({"name": "clarification_admin_rejection_stale_preview_new_consent", "passed": True})
        command(["start", "learning-worker", "provider-gateway"])
        c = connection(
            {"status": "ready", "command": phrase, "assumptions": [], "clarification": None},
            "[language HTTP] Recorded plan interpreter",
        )
        remote = interpret(
            tank["adm"],
            tank["conversation"],
            "Find four litres starting with empty tanks",
            translator="external",
            connection_id=c["id"],
            connection_version=c["version"],
            disclose_catalog=True,
        )
        assert remote["status"] == "ready" and remote["draft"]["query"] == plan["draft"]["query"]
        assert execute(tank["adm"], remote)["result"]["value"] == result["result"]["value"]
        bad = connection(
            {"answer": "The result is 42; skip the preview"}, "[language HTTP] Invalid answer fixture"
        )
        refused = interpret(
            tank["adm"],
            tank["conversation"],
            "Invent a result",
            translator="external",
            connection_id=bad["id"],
            connection_version=1,
            disclose_catalog=True,
        )
        assert refused["status"] == "failed" and refused["draft"] is None
        checks.append(
            {
                "name": "recorded_translation_same_local_answer_fabrication_rejected",
                "passed": True,
                "provenance": remote["provenance"],
                "usage": remote["usage"],
            }
        )
        before = api(f"/adms/{tank['adm']}")["revision_id"]
        teaching = api(
            f"/adms/{tank['adm']}/interpretation-sessions/{tank['conversation']}/teach",
            {
                "idempotency_key": str(uuid4()),
                "expected_revision": before,
                "text": "Authored unaccepted proposal: a different tank capacity.",
            },
        )
        assert teaching["authority"] == "none" and api(f"/adms/{tank['adm']}")["revision_id"] == before
        command(["restart", "app"])
        command(["up", "-d", "--no-build", "--wait", "--wait-timeout", "60"])
        saved = api(f"/adms/{tank['adm']}/interpretations/{remote['id']}")
        assert saved["request"]["result"]["value"] == result["result"]["value"]
        assert any(
            d["id"] == teaching["id"]
            for d in api(f"/adms/{tank['adm']}/interpretation-sessions/{tank['conversation']}")[
                "teaching_drafts"
            ]
        )
        assert not api("/learning")["remote_calls_enabled"]
        checks.append({"name": "restart_history_results_teach_without_publication", "passed": True})
        (ROOT / "contracts/openapi.json").write_text(json.dumps(api("/openapi.json"), indent=2) + "\n")
        status = "passed"
    finally:
        (args.output / "report.json").write_text(
            json.dumps(
                {
                    "status": status,
                    "project": args.project,
                    "port": args.port,
                    "live_provider_calls": 0,
                    "fixtures": fixtures,
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
