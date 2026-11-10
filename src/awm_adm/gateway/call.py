"""One network-capable child; its parent enforces the whole-call wall deadline."""

import math
import os
import resource
import signal
import subprocess
import sys
import time

from ..providers.transport import acquire
from ..runtime.protocol import dumps, loads


def bounded_acquire(configuration, wire, credential, timeout, *, recorded_index=0):
    body = dumps(
        {"configuration": configuration, "wire": wire.decode(), "credential": credential, "timeout": timeout}
    )
    end = time.monotonic() + timeout
    process = subprocess.Popen(
        [sys.executable, "-I", "-m", "awm_adm.gateway.call", str(os.getpid())],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env={"PATH": os.defpath, "LANG": "C.UTF-8"},
        cwd="/tmp",
    )
    try:
        output, _ = process.communicate(body, timeout=max(0.001, end - time.monotonic()))
        if process.returncode != 0 or len(output) > 1_048_576:
            raise ValueError("Incomplete gateway child")
        return loads(output)
    except (subprocess.TimeoutExpired, ValueError):
        return {"status": "outcome_unknown", "error": "transport_uncertain", "usage": None, "text": None}
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def main():
    body = loads(sys.stdin.buffer.read(2_097_153))
    if len(dumps(body)) > 2_097_152:
        return 1
    seconds = max(1, math.ceil(body["timeout"])) + 1
    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (536_870_912, 536_870_912))
        import ctypes

        parent = int(sys.argv[1])
        ctypes.CDLL(None).prctl(1, signal.SIGKILL)
        if os.getppid() != parent:
            return 1
    outcome = acquire(body["configuration"], body["wire"].encode(), body["credential"], body["timeout"])
    sys.stdout.buffer.write(dumps(outcome))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
