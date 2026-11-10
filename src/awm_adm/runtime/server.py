"""Two listeners: public status/assets and unpublished authenticated control."""

import argparse
import json
import threading
import time
from pathlib import Path

import uvicorn

from ..api import create_app
from ..config import load_config
from .http import create_internal, secret
from .service import Runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("/opt/awm-adm/config.toml"))
    parser.add_argument("--secrets", type=Path, default=Path("/run/secrets"))
    parser.add_argument("--assets", type=Path, default=Path("/opt/awm-adm/console"))
    args = parser.parse_args()
    tokens = {name: secret(args.secrets / f"{name}-token") for name in ("owner", "worker", "gateway")}
    runtime = Runtime(load_config(args.config))
    internal = uvicorn.Server(
        uvicorn.Config(
            create_internal(runtime, tokens),
            host="0.0.0.0",
            port=8081,
            access_log=False,
            proxy_headers=False,
            timeout_graceful_shutdown=5,
        )
    )
    thread = threading.Thread(target=internal.run, daemon=True)
    public = uvicorn.Server(
        uvicorn.Config(
            create_app(runtime.config, runtime=runtime, assets=args.assets, owner_token=tokens["owner"]),
            host="0.0.0.0",
            port=runtime.config.server.port,
            access_log=False,
            proxy_headers=False,
            timeout_graceful_shutdown=5,
        )
    )
    stop = threading.Event()

    def heartbeat():
        path = Path("/tmp/awm-adm-health.json")
        while not stop.wait(2):
            try:
                ready = (
                    public.started
                    and internal.started
                    and thread.is_alive()
                    and runtime.status()["local_serving"]
                )
                staged = path.with_suffix(".new")
                staged.write_text(json.dumps({"updated": time.monotonic(), "ready": ready}))
                staged.replace(path)
            except Exception:
                pass

    health = threading.Thread(target=heartbeat, daemon=True)
    try:
        thread.start()
        deadline = time.monotonic() + 5
        while not internal.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Internal control listener could not start")
            time.sleep(0.02)
        health.start()
        public.run()
    finally:
        stop.set()
        internal.should_exit = True
        runtime.supervisor.close()
        thread.join(timeout=10)
        runtime.close()


if __name__ == "__main__":
    main()
