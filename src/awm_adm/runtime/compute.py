"""Trusted one-shot local computation. Receives immutable data, never store handles."""

import math
import os
import resource
import socket
import sys

from ..engine import Budget, Instance, validate_snapshot
from ..engine.artifacts import digest
from ..engine.conformance import validate_policy, verify_policy
from ..engine.data import encode
from ..engine.errors import ADMError, ResourceLimit
from ..engine.execution import execute, normalize_query
from ..engine.lean_backend import LeanBackend
from ..engine.results import bind_result
from ..engine.snapshots import export_instance
from .protocol import MAX_MESSAGE, dumps, loads, pack, unpack


def compute(task):
    limits = task["limits"]
    budget = Budget(limits["max_work"], limits["max_duration_ms"] / 1000)
    if task["operation"].startswith("teaching_"):
        from ..teaching.compute import compute as teaching_compute

        return teaching_compute(task, budget)
    if task["operation"].startswith("source_"):
        from ..sources.compute import compute as source_compute

        return source_compute(task, budget)
    if task["operation"].startswith("language_"):
        from ..language.compute import compute as language_compute

        return language_compute(task, budget)
    if task["operation"].startswith("learning_"):
        from ..learning.compute import compute as learning_compute

        return learning_compute(task, budget)
    if task["operation"] == "prepare":
        instance = (
            Instance.restore(unpack(task["snapshot"]), mode=task["mode"], budget=budget)
            if task.get("snapshot") is not None
            else Instance(mode=task["mode"], budget=budget)
        )
        snapshot = instance.export_snapshot(state=instance.initial_state(), budget=budget)
        return {"snapshot": pack(snapshot), "context": instance.info()}
    if task["operation"] in ("export", "requirements"):
        checked = validate_snapshot(unpack(task["snapshot"]), budget=budget)
        policy = (
            validate_policy(task["policy"], budget=budget)
            if task["operation"] == "requirements"
            else checked["conformance"]
        )
        verify_policy(policy, checked["model"], budget=budget)
        pinned = {
            "instance_id": task["context"]["instance_id"],
            "model": checked["model"],
            "policy": encode(policy),
            "blobs": checked["blobs"],
            "support": checked["support"],
            "lineage": checked["lineage"],
        }
        snapshot = export_instance(pinned, state=checked["state"], budget=budget)
        context = {**task["context"], "conformance_root": digest(encode(policy))}
        return {"snapshot": pack(snapshot), "context": context}
    if task["operation"] != "query":
        raise ValueError("Unsupported compute operation")
    # Cold admission, owner checks and actual execution share the same request budget.
    try:
        checked = validate_snapshot(unpack(task["snapshot"]), budget=budget)
    except ResourceLimit as error:
        result = {"status": "inconclusive", "error": error.as_dict(), "guarantee": None, "work": budget.used}
        bind_result(task["context"]["theory_version"], task["query"], result, [])
        return result
    model = checked["model"]
    context = task["context"]
    if context["theory_version"] != model.version or context["support_root"] != digest(
        encode(checked["support"])
    ):
        raise ValueError("Pinned model context does not match checked snapshot")
    from ..sources.compute import query as source_query

    try:
        result = source_query(checked, task["query"], limits, budget)
    except ResourceLimit as error:
        result = bind_result(
            model.version,
            task["query"],
            {"status": "inconclusive", "error": error.as_dict(), "work": budget.used},
            [],
        )
    except ADMError as error:
        result = bind_result(
            model.version,
            task["query"],
            {"status": "needs_input", "error": error.as_dict(), "work": budget.used},
            [],
        )
    if result is not None:
        return result
    query = normalize_query(task["query"], limits)
    lean = LeanBackend(task["lean_executable"]) if task.get("lean_executable") else None
    explain = (lambda _uid: task["explanation"]) if "explanation" in task else None
    return execute(model, query, limits, budget=budget, lean=lean, explain=explain)


def main():
    try:
        task = loads(sys.stdin.buffer.read(MAX_MESSAGE + 1))
        seconds = math.ceil(task["limits"]["max_duration_ms"] / 1000) + 2
        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_MESSAGE, MAX_MESSAGE))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
        if sys.platform == "linux":
            # Lean's bundled runtime needs more than 1 GiB of virtual address
            # space even for a tiny proof. RSS is also bounded by the app cgroup.
            resource.setrlimit(resource.RLIMIT_AS, (2_147_483_648, 2_147_483_648))

        def denied(*args, **kwargs):
            raise RuntimeError("Local computation cannot open network connections")

        socket.socket.connect = denied
        socket.create_connection = denied
        socket.getaddrinfo = denied
        # Parent-death signal also bounds orphaned work after an app SIGKILL on Linux.
        if sys.platform == "linux":
            import ctypes
            import signal

            parent = int(sys.argv[1])
            ctypes.CDLL(None).prctl(1, signal.SIGKILL)
            if os.getppid() != parent:
                return 1
        response = {"ok": True, "value": compute(task)}
    except ADMError as error:
        response = {"ok": False, "error": error.code}
    except Exception:
        response = {"ok": False, "error": "invalid_compute_input"}
    sys.stdout.buffer.write(dumps(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
