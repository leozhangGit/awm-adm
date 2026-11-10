"""Idle component protocol skeletons. No provider calls or accepted-state access."""

import argparse
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .http import secret


def exchange(url, token, body=None, *, timeout=3):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    # Internal service traffic never uses a host or inherited HTTP proxy.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        request, timeout=timeout
    ) as response:
        from .protocol import MAX_MESSAGE, loads

        return loads(response.read(MAX_MESSAGE + 1))


def component_app(role, state):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health/live")
    def live():
        return {"status": "live", "role": role}

    @app.get("/health/ready")
    def ready():
        valid = time.monotonic() - state["heartbeat"] < 15
        return JSONResponse(
            {
                "status": "ready" if valid else "not_ready",
                "role": role,
                "learning": True,
                "provider_calls": role == "gateway",
            },
            status_code=200 if valid else 503,
        )

    @app.post("/internal/dispatch")
    def dispatch():
        return JSONResponse(
            {"error": "provider_transport_not_implemented", "dispatched": False}, status_code=501
        )

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("worker", "gateway"))
    parser.add_argument("--app-url", default="http://app:8081")
    args = parser.parse_args()
    role = args.role
    token = secret(f"/run/secrets/{role}-token")
    state = {"heartbeat": float("-inf")}
    stop = threading.Event()
    gateway = None
    if role == "gateway":
        from ..gateway.service import Gateway, application
        from ..gateway.store import GatewayStore

        vault = GatewayStore(
            "/var/lib/awm-gateway",
            Path("/run/secrets/gateway-master-key").read_bytes().strip(),
            static_dir="/run/provider-secrets",
        )
        gateway = Gateway(
            vault, lambda route, body: exchange(args.app_url + "/internal/m5/" + route, token, body)
        )
        app = application(gateway, secret("/run/secrets/worker-token"), state)
    else:
        app = component_app(role, state)

    def heartbeat():
        lease = None
        while not stop.is_set():
            try:
                if lease is None:
                    lease = exchange(args.app_url + "/internal/m2/components/claim", token, {})
                exchange(args.app_url + "/internal/m2/components/renew", token, lease)
                state["heartbeat"] = time.monotonic()
                if gateway:
                    gateway.synchronize()
            except (OSError, ValueError):
                lease = None
            stop.wait(3)

    def work():
        while not stop.is_set():
            try:
                job = exchange(args.app_url + "/internal/m5/claim", token, {})["job"]
                if job:
                    exchange(
                        "http://provider-gateway:8090/internal/dispatch",
                        token,
                        {"grant_id": job["grant_id"], "lease": job["lease"]},
                        timeout=job["timeout_ms"] / 1000 + 3,
                    )
                    continue
            except (OSError, ValueError):
                pass  # Never repeat a dispatched lease; app retains uncertainty.
            stop.wait(0.5)

    workers = [threading.Thread(target=work, daemon=True) for _ in range(2)] if role == "worker" else []
    for worker in workers:
        worker.start()
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        uvicorn.run(app, host="0.0.0.0", port=8090, access_log=False)
    finally:
        stop.set()
        thread.join(timeout=7)
        if gateway:
            gateway.store.close()


if __name__ == "__main__":
    main()
