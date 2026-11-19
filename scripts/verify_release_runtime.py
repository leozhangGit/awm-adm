"""Exercise direct Enable/Teach/Ask in a disposable Docker fixture stack, never a live provider."""

import argparse
import base64
import http.cookiejar
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

EMAIL = "owner@example.test"
PASSWORD = "synthetic walkthrough passphrase"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--override", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8089)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        not args.project.startswith("awm-adm-check-release-")
        or args.port in (8080, 8081)
        or not 1024 <= args.port <= 65535
    ):
        raise ValueError("Use a dedicated release project and nonproduction port")
    root = args.package.resolve()
    override = (root / args.override).resolve()
    if not override.is_file():
        raise ValueError("Compose override must exist")
    config = override.read_text()
    if "runtime_fixture_gateway.py" not in config or "networks: !override [internal]" not in config:
        raise ValueError("Require a synthetic gateway with no provider-egress network")
    args.output.mkdir(parents=True, exist_ok=False)
    compose = ["docker", "compose", "-p", args.project, "-f", "compose.yaml", "-f", str(override)]
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    csrf = None

    def api(path, body=None, method=None, *, origin=False):
        headers = {"Content-Type": "application/json"}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        if origin:
            headers["X-ADM-Client"] = "console"
        request = urllib.request.Request(
            f"http://localhost:{args.port}/api/v1" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method or ("POST" if body is not None else "GET"),
        )
        with opener.open(request, timeout=30) as response:
            return json.load(response)

    def wait(read, predicate, seconds=120):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                value = read()
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.25)
                continue
            if predicate(value):
                return value
            if value.get("status") in {"failed", "cancelled", "exhausted", "needs_input"}:
                raise AssertionError(value)
            time.sleep(0.25)
        raise AssertionError(value)

    def command(*arguments):
        subprocess.run([*compose, *arguments], cwd=root, check=True, capture_output=True, timeout=120)

    def create(name, snapshot=None):
        op = api(
            "/adms",
            {"name": name, "idempotency_key": str(uuid4()), **({"snapshot": snapshot} if snapshot else {})},
        )
        return wait(lambda: api("/operations/" + op["operation_id"]), lambda v: v["status"] == "succeeded")[
            "result"
        ]["adm_id"]

    def local(key, year, expected):
        query = {
            "op": "lookup_fact",
            "entity_id": "camera-kit",
            "predicate": "equipment.capacity",
            "effective_at": f"{year}-01-01T00:00:00Z",
        }
        item = api(f"/adms/{key}/requests", {"query": query, "idempotency_key": str(uuid4())})
        result = wait(
            lambda: api(f"/adms/{key}/requests/{item['request_id']}"),
            lambda v: v["status"] in {"succeeded", "needs_input"},
        )
        assert result["status"] == ("needs_input" if expected is None else "succeeded"), result
        if expected is not None:
            assert result["result"]["value"]["value"] == expected, result
        return result

    assert api("/auth/status")["setup_required"]
    # This is a new, isolated test account and a synthetic provider key only.
    api(
        "/auth/setup",
        {
            "bootstrap_token": (root / ".local/secrets/owner-token").read_text().strip(),
            "email": EMAIL,
            "password": PASSWORD,
        },
    )
    csrf = api("/auth/me")["csrf"]
    assert not api("/adms")["items"]
    state = wait(lambda: api("/connection"), lambda v: bool(v.get("gateway_key")))
    public = state["gateway_key"]
    identity = str(uuid4())
    key = serialization.load_der_public_key(base64.b64decode(public["spki"]))
    encrypted = key.encrypt(
        json.dumps(
            {"credential": "synthetic-test-secret", "provider": "openai", "idempotency_key": identity}
        ).encode(),
        padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=b"awm-adm-provider-credential/1",
        ),
    )
    enable = {
        "idempotency_key": identity,
        "provider": "openai",
        "model": "synthetic-equipment-model",
        "sealed_credential": base64.b64encode(encrypted).decode(),
        "sealing_key_id": public["key_id"],
    }
    activation = api("/connection/enable", enable)
    wait(lambda: api("/connection"), lambda v: v["state"] == "enabled")
    assert api("/connection/enable", enable)["id"] == activation["id"]
    model = create("Equipment cleanup rehearsal")
    item = api(
        f"/adms/{model}/attachments",
        {
            "idempotency_key": str(uuid4()),
            "name": "history.md",
            "media_type": "text/markdown",
            "content": (root / "examples/teaching/history.md").read_text(),
        },
    )
    teaching = api(
        f"/adms/{model}/teach",
        {"text": (root / "examples/teaching/teach.txt").read_text(), "attachments": [item["id"]]},
        origin=True,
    )
    teaching = wait(
        lambda: api(f"/adms/{model}/interactions/{teaching['id']}"),
        lambda v: v["status"] == "succeeded" and bool(v.get("explanation")),
    )
    answers = []
    for text, expected in [
        ("Can I borrow one more item if I have one and one is available?", True),
        ("What was camera-kit capacity at 2026-01-01 midnight UTC?", 1),
        ("What was camera-kit capacity at 2027-01-01 midnight UTC?", None),
    ]:
        item = api(f"/adms/{model}/ask", {"text": text}, origin=True)
        item = wait(
            lambda: api(f"/adms/{model}/interactions/{item['id']}"), lambda v: v["status"] == "completed"
        )
        result = api(f"/adms/{model}/requests/{item['request_id']}")
        assert result["status"] == ("needs_input" if expected is None else "succeeded"), result
        if expected is not None:
            assert result["result"]["value"]["value"] == expected, result
        assert item["explanation"] and item["outcome"]["request_id"] == result["request_id"]
        answers.append(item)
    assert len(api(f"/adms/{model}/chat/ask")["items"]) == 3
    assert len(api(f"/adms/{model}/activity?origin=console")["items"]) == 4
    assert api(f"/adms/{model}/knowledge")["items"]
    snapshot = api(f"/adms/{model}/snapshot-exports", {"idempotency_key": str(uuid4())})
    snapshot = wait(
        lambda: api("/operations/" + snapshot["operation_id"]), lambda v: v["status"] == "succeeded"
    )["result"]["snapshot"]
    clone = create("Equipment snapshot copy", snapshot)
    usage = api("/learning")["usage"]
    command("stop", "provider-gateway")
    try:
        lookups = [local(clone, year, expected) for year, expected in ((2025, 2), (2026, 1), (2027, None))]
        assert api("/learning")["usage"] == usage
    finally:
        command("start", "provider-gateway")
    api("/connection/disable", {"idempotency_key": str(uuid4())})
    command("restart", "app")
    wait(lambda: api("/auth/me"), lambda v: bool(v.get("administrator")))
    assert api("/connection")["state"] == "disabled"
    assert len(api(f"/adms/{model}/chat/ask")["items"]) == 3
    assert api("/learning")["usage"] == usage
    report = {
        "status": "passed",
        "real_provider_calls": 0,
        "model": model,
        "clone": clone,
        "teaching": teaching,
        "answers": answers,
        "offline_lookups": lookups,
        "usage": usage,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": "passed", "model": model, "clone": clone, "real_provider_calls": 0}))


if __name__ == "__main__":
    main()
