"""Persistent runtime hosting private operators and durable application requests."""

import subprocess
from threading import RLock

from ..application.store import ApplicationStore as Store
from ..engine.artifacts import digest
from ..engine.data import encode
from ..engine.execution import normalize_query
from ..engine.results import semantic_query
from .protocol import RuntimeFault
from .supervisor import Supervisor


class Runtime:
    def __init__(self, config, *, start_scheduler=True):
        self.config = config
        self._lock = RLock()
        self._closed = False
        self.store = Store(config.server.data_dir, config.runtime)
        try:
            self.supervisor = Supervisor(config.runtime.serving_processes)
            self.lean = self._lean_status()
            from ..lifecycle.service import Lifecycle

            self.lifecycle = Lifecycle(self)
            from ..application.coordinator import Coordinator

            self.coordinator = Coordinator(self, start=start_scheduler)
            from ..learning.service import LearningService

            self.learning = LearningService(self, start=start_scheduler)
            from ..language.service import LanguageService

            self.language = LanguageService(self, start=start_scheduler)
            from ..sources.service import SourceService

            self.sources = SourceService(self, start=False)
            from ..conversations.service import Conversations

            self.conversations = Conversations(self, start=False)
            self.lifecycle.ready = True
            if start_scheduler:
                self.conversations.start_worker()
                self.sources.start_worker()
        except BaseException:
            for name in ("conversations", "sources", "language", "learning", "coordinator"):
                component = getattr(self, name, None)
                if component is not None:
                    component.close()
            self.store.close()
            raise

    def _lean_status(self):
        try:
            result = subprocess.run(
                [self.config.proof.lean_executable, "--version"], capture_output=True, timeout=5, text=True
            )
            valid = result.returncode == 0 and result.stdout.startswith("Lean (version 4.19.0,")
            return {"available": valid, "version": "4.19.0" if valid else None}
        except (OSError, subprocess.TimeoutExpired):
            return {"available": False, "version": None}

    def status(self):
        components = self.store.components()
        return {
            "local_serving": not self._closed,
            "lean": self.lean["available"],
            "worker": components["worker"],
            "gateway": components["gateway"],
            "learning": not self._closed,
            "providers": components["gateway"],
            "language": not self._closed,
        }

    def limits(self, requested=None):
        maximum = self.config.request.model_dump()
        value = {**maximum, **(requested or {})}
        if set(value) != set(maximum) or any(
            type(v) is not int or v < 1 or v > maximum[k] for k, v in value.items()
        ):
            raise RuntimeFault("invalid_limits", "Request limits must be positive and within configured caps")
        return value

    def create(self, name, *, mode=None, snapshot=None):
        mode = mode or self.config.learning.default_conflict_mode
        if mode not in ("forward", "backward"):
            raise RuntimeFault("invalid_input", "Unknown conflict mode")
        key = self.store.reserve(name)
        try:
            prepared = self.supervisor.run(
                {"operation": "prepare", "mode": mode, "snapshot": snapshot, "limits": self.limits()}
            )
            return self.store.install(key, prepared, mode)
        except BaseException:
            self.store.failed_creation(key)
            raise

    def query(self, key, query, *, limits=None):
        caps = self.limits(limits)
        if query.get("op") == "lookup_fact":
            from ..contracts import FactLookup

            query = FactLookup.model_validate(query).model_dump()
        else:
            query = normalize_query(query, caps)
        with self._lock:
            context = self.store.info(key)
            snapshot = self.store.snapshot(key)
            lease = self.store.claim(key, query, context, caps["max_duration_ms"] / 1000 + 3)
        try:
            result = self.supervisor.run(
                {
                    "operation": "query",
                    "snapshot": snapshot,
                    "context": context,
                    "query": query,
                    "limits": caps,
                    "lean_executable": self.config.proof.lean_executable,
                }
            )
            binding = result.get("binding", {})
            body = {k: v for k, v in binding.items() if k != "digest"}
            if (
                binding.get("profile") != "adm-result/0.1"
                or binding.get("theory_version") != context["theory_version"]
                or encode(binding.get("query")) != encode(semantic_query(query))
                or binding.get("digest") != digest(encode(body))
            ):
                raise RuntimeFault("invalid_result", "Child result does not match the pinned operation")
            result["execution"] = {
                "instance_id": key,
                "theory_version": context["theory_version"],
                "policy_epoch": context["policy_epoch"],
                "support_root": context["support_root"],
                "attempt_id": lease["token"],
                "run_id": lease["id"],
            }
            self.store.finish(key, lease, result)
            return self.store.run_info(key, lease["id"])
        except BaseException:
            self.store.abandon(key, lease, "interrupted")
            raise

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                self.conversations.close()
                self.sources.close()
                self.language.close()
                self.learning.close()
                self.coordinator.close()
                # Revoke every outstanding generation before releasing ownership.
                for row in self.store.list():
                    if row["status"] == "ready":
                        with self.store.db(row["id"]) as connection:
                            connection.execute(
                                "UPDATE runs SET status='interrupted', result=NULL WHERE status='running'"
                            )
                self.store.close()
