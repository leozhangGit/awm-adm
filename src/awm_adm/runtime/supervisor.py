"""Bounded process supervision with group termination and a clean environment."""

import os
import signal
import subprocess
import sys
import tempfile
import time
from threading import BoundedSemaphore, Lock

from ..operations.metrics import Metrics
from .protocol import MAX_MESSAGE, RuntimeFault, dumps, loads


class Supervisor:
    def __init__(self, capacity=2):
        self.metrics = Metrics()
        self._slots = BoundedSemaphore(capacity)
        self._lock = Lock()
        self._processes = {}
        self._cancelled_scopes = set()
        self._closed = False

    @staticmethod
    def _kill(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()

    def cancel_scope(self, scope):
        with self._lock:
            self._cancelled_scopes.add(scope)
            for process, owner in self._processes.items():
                if owner == scope:
                    self._kill(process)

    def run(self, task, *, cancel=None, scope=None):
        scope = scope or task.get("context", {}).get("instance_id")
        started = time.monotonic()
        status = "ok"
        consumed = None
        if not self._slots.acquire(blocking=False):
            self.metrics.record("busy", 0)
            raise RuntimeFault("busy", "Local compute capacity is occupied")
        process = None
        try:
            data = dumps(task)
            timeout = task["limits"]["max_duration_ms"] / 1000 + 2
            with (
                tempfile.TemporaryDirectory(prefix="awm-adm-compute-") as directory,
                tempfile.TemporaryFile() as output,
                tempfile.TemporaryFile() as input_file,
            ):
                input_file.write(data)
                input_file.seek(0)
                environment = {"PATH": os.defpath, "LANG": "C.UTF-8", "TMPDIR": directory}
                with self._lock:
                    if scope is not None and scope in self._cancelled_scopes:
                        raise RuntimeFault("gone", "Model compute authority was revoked")
                    if self._closed:
                        raise RuntimeFault("stopped", "Compute supervisor is stopping")
                    process = subprocess.Popen(
                        [sys.executable, "-I", "-m", "awm_adm.runtime.compute", str(os.getpid())],
                        stdin=input_file,
                        stdout=output,
                        stderr=subprocess.DEVNULL,
                        cwd=directory,
                        env=environment,
                        start_new_session=True,
                    )
                    self._processes[process] = scope
                deadline = time.monotonic() + timeout
                while True:
                    if cancel is not None and cancel.is_set():
                        raise RuntimeFault("cancelled", "Local attempt was cancelled")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeFault("resource_exhausted", "Local computation exceeded its deadline")
                    try:
                        process.wait(timeout=min(remaining, 0.1))
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if process.returncode:
                    raise RuntimeFault(
                        "compute_failed", "Local computation stopped without a complete result"
                    )
                output.seek(0)
                response = loads(output.read(MAX_MESSAGE + 1))
                if not response.get("ok"):
                    raise RuntimeFault(response["error"], "Local checking could not complete the operation")
                value = response["value"]
                consumed = value.get("work") if isinstance(value, dict) else None
                return value
        except RuntimeFault as error:
            status = error.code
            raise
        except BaseException:
            status = "other_failure"
            raise
        finally:
            self.metrics.record(
                status, time.monotonic() - started, task.get("limits", {}).get("max_work", 0), consumed
            )
            if process is not None:
                # Kill the complete group, including any compiler descendant, even
                # if the Python child has already exited.
                self._kill(process)
                with self._lock:
                    self._processes.pop(process, None)
            self._slots.release()

    def close(self):
        with self._lock:
            self._closed = True
            for process in self._processes:
                self._kill(process)
