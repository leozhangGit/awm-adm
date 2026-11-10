"""Gateway authority: decrypt locally, fence dispatch durably, deliver only final output."""

import base64
import hashlib
import secrets
import time
from threading import BoundedSemaphore

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from ..learning.http import Dispatch
from ..providers.transport import acquire
from ..runtime.http import BodyLimit
from ..runtime.protocol import loads


class Gateway:
    def __init__(self, store, exchange, *, transport=None):
        self.store, self.exchange, self.transport = store, exchange, transport
        self.acknowledgments = []
        self.deletion_acknowledgments = []
        self.slots = BoundedSemaphore(2)

    def synchronize(self):
        response = self.exchange(
            "synchronize",
            {
                "public_key": self.store.public,
                "acknowledgments": self.acknowledgments,
                "deletion_acknowledgments": self.deletion_acknowledgments,
            },
        )
        self.acknowledgments = []
        self.deletion_acknowledgments = []
        for grant in response.get("deletions", []):
            self.store.forget(grant)
            self.deletion_acknowledgments.append(grant)
        for config in response["connections"]:
            status = "ready"
            try:
                self.store.install(config)
            except Exception:
                status = "credential_unavailable"
            self.acknowledgments.append(
                {
                    "id": config["id"],
                    "version": config["version"],
                    "configuration_digest": config["configuration_digest"],
                    "status": status,
                }
            )
        with self.store.db() as db:
            rows = db.execute(
                "SELECT * FROM dispatches WHERE result IS NOT NULL AND acknowledged=0 ORDER BY created LIMIT 20"
            ).fetchall()
        for row in rows:
            self.deliver(row)

    def deliver(self, row):
        with self.store.lock:
            return self._deliver(self.store.lookup(row["id"]))

    def _deliver(self, row):
        if not row["request"]:
            return
        request = loads(row["request"])
        self.exchange(
            "outcome", {"grant_id": row["id"], "lease": request["lease"], "outcome": loads(row["result"])}
        )
        with self.store.db() as db:
            db.execute("UPDATE dispatches SET acknowledged=1 WHERE id=?", (row["id"],))

    def dispatch(self, grant_id, lease):
        if not self.slots.acquire(blocking=False):
            raise ValueError("Gateway dispatch capacity occupied")
        try:
            return self._dispatch(grant_id, lease)
        finally:
            self.slots.release()

    def _dispatch(self, grant_id, lease):
        old = self.store.lookup(grant_id)
        if old:
            if not old["request"]:
                return {"status": "not_dispatched", "replayed": True}
            request = loads(old["request"])
            if not secrets.compare_digest(request["lease"], lease):
                raise ValueError("Wrong dispatch lease")
            if old["result"]:
                self.deliver(old)
            return {"status": old["status"], "replayed": True}
        body = self.exchange("authorize", {"grant_id": grant_id, "lease": lease})
        from ..contracts import DispatchGrant

        checked = DispatchGrant.model_validate(body["grant"])
        if (
            checked.grant_id != grant_id
            or checked.lease.lease_token != lease
            or checked.request_digest != body["provenance"]["request_hash"]
        ):
            raise ValueError("Dispatch contract mismatch")
        config, key = self.store.connection(
            body["connection_id"], body["connection_version"], body["configuration_digest"]
        )
        if checked.lease.purpose != body["purpose"] or body["purpose"] not in config["purposes"]:
            raise ValueError("Grant purpose does not match the exact connection authority")
        if config["provider"] != "recorded" and not body.get("price_binding"):
            raise ValueError("Remote dispatch requires priced authority")
        wire = base64.b64decode(body["wire"], validate=True)
        digest = "sha256:" + hashlib.sha256(wire).hexdigest()
        if digest != body["provenance"]["request_hash"] or body["expires"] <= time.time():
            raise ValueError("Invalid or expired dispatch wire")
        if not self.store.begin(grant_id, digest, body):
            return {"status": "dispatched", "replayed": True}
        if config["provider"] == "recorded" and body["purpose"] == "connection_test":
            config = {**config, "recorded_responses": [{"ok": True}]}
        options = {"transport": self.transport} if self.transport else {}
        from .call import bounded_acquire

        runner = bounded_acquire if self.transport is None and config["provider"] != "recorded" else acquire
        outcome = runner(
            config,
            wire,
            key,
            max(0.001, min(body["limits"]["max_duration_ms"] / 1000, body["expires"] - time.time())),
            recorded_index=body["recorded_index"],
            **options,
        )
        key = None
        self.store.finish(grant_id, outcome)
        self.deliver(self.store.lookup(grant_id))
        return {"status": outcome["status"], "replayed": False}


def application(gateway, worker_token, state):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimit, maximum=4096)

    @app.get("/health/live")
    def live():
        return {"status": "live", "role": "gateway"}

    @app.get("/health/ready")
    def ready():
        valid = time.monotonic() - state["heartbeat"] < 15
        return JSONResponse(
            {"status": "ready" if valid else "not_ready", "role": "gateway", "learning": True},
            status_code=200 if valid else 503,
        )

    @app.post("/internal/dispatch")
    def dispatch(request: Request, body: Dispatch):
        if not secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + worker_token):
            raise HTTPException(403, "Worker authority required")
        try:
            return gateway.dispatch(body.grant_id, body.lease)
        except Exception:
            # Provider/credential errors must not echo raw exception content.
            return JSONResponse({"error": "dispatch_unavailable", "retry": "reconcile"}, status_code=503)

    return app
