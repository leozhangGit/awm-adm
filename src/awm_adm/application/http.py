"""Versioned owner/client API, safe input boundary and retained event streaming."""

import asyncio
import json
import time
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi import Request as HTTPRequest
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer
from pydantic import Field
from starlette.exceptions import HTTPException

from ..contracts import ClosedModel, Identifier, Request
from ..runtime.protocol import RuntimeFault, dumps
from ..wire import decode
from .auth import Authority
from .models import Operation, RequestPage, RequestView
from .store import failure


class Create(ClosedModel):
    idempotency_key: Identifier
    name: str = Field(min_length=1, max_length=128)
    mode: Literal["forward", "backward"] = "backward"
    snapshot: dict | None = None


class Change(ClosedModel):
    expected_epoch: int = Field(ge=0)
    mode: Literal["forward", "backward"]


class Policy(ClosedModel):
    expected_epoch: int = Field(ge=0)
    policy: dict


class Epoch(ClosedModel):
    expected_epoch: int = Field(ge=0)


class Cursor(ClosedModel):
    cursor: int = Field(default=0, ge=0, le=9_007_199_254_740_991)


class Export(ClosedModel):
    idempotency_key: Identifier


class Token(ClosedModel):
    adms: list[str] = Field(min_length=1, max_length=100)
    permissions: list[Literal["read", "submit"]] = Field(min_length=1, max_length=2)
    expires_in: int = Field(default=3600, ge=60, le=2_592_000)


CODES = {
    "unauthorized": 401,
    "forbidden": 403,
    "remote_calls_disabled": 403,
    "connection_unavailable": 409,
    "purpose_unavailable": 409,
    "allowance_expired": 409,
    "allowance_closed": 409,
    "allowance_exhausted": 409,
    "allowance_unavailable": 409,
    "price_unavailable": 409,
    "spending_disabled": 403,
    "spending_suspended": 403,
    "not_found": 404,
    "gone": 410,
    "conflict": 409,
    "stale_context": 409,
    "cursor_expired": 410,
    "quota_exceeded": 429,
    "resource_exhausted": 429,
    "busy": 429,
    "rate_limited": 429,
    "intake_full": 429,
    "needs_specification": 422,
    "unsupported": 422,
    "not_implemented": 501,
    "invalid_input": 422,
    "invalid_limits": 422,
}


def error_response(code, status=None):
    if code in {"invalid_ir", "conformance_failed", "rejected", "invalid_compute_input"}:
        code = "invalid_input"
    public = code if code in CODES else "internal_error"
    messages = {
        "unauthorized": "Authentication required or expired",
        "forbidden": "Operation is not authorized",
        "remote_calls_disabled": "Remote AI calls are disabled. Review Connections; the model remains available in Local debug",
        "connection_unavailable": "The connection is disabled or not ready. Review Connections",
        "purpose_unavailable": "The required connection purpose is disabled. Review Connections",
        "allowance_expired": "This conversation's allowance expired. Review a new allowance before sending",
        "allowance_closed": "This conversation's allowance is closed. Review a new allowance before sending",
        "allowance_exhausted": "This conversation's call, token or cost allowance is used up. Review a new allowance",
        "allowance_unavailable": "This allowance cannot currently reserve work. Review spending limits in Connections",
        "price_unavailable": "The price expired or the connection changed. Review pricing and a new allowance",
        "spending_disabled": "Installation spending is disabled. Review limits in Connections",
        "spending_suspended": "This spending lane requires owner review after a usage overrun",
        "not_found": "Resource not found in this scope",
        "gone": "This model is being deleted or has been deleted",
        "conflict": "Input conflicts with the recorded operation or state",
        "stale_context": "Context changed; reload before editing or submitting new work",
        "cursor_expired": "Event history expired; reload current resources and resume at earliest_cursor",
        "quota_exceeded": "Configured capacity is exhausted",
        "resource_exhausted": "Configured resource allowance is exhausted",
        "busy": "Local compute capacity is occupied",
        "rate_limited": "Source intake rate reached; wait at least 60 seconds and retry the same submission identity",
        "intake_full": "Source intake queue is full; retry the same identity after pending material is processed",
        "needs_specification": "Source scope needs clarification before execution; review coverage, material and current policy",
        "invalid_input": "Input does not match the API contract",
        "invalid_limits": "Requested limits exceed configured caps",
        "unsupported": "Operation is unsupported",
        "not_implemented": "Capability is not implemented",
        "internal_error": "Operation could not complete",
    }
    retry = (
        "resynchronize"
        if public == "cursor_expired"
        else "after_backoff"
        if public in ("busy", "quota_exceeded", "rate_limited", "intake_full")
        else "after_input"
    )
    return JSONResponse(failure(public, messages[public], retry), status_code=status or CODES.get(code, 503))


class Boundary:
    def __init__(self, app, maximum, port):
        self.app, self.maximum, self.port = app, maximum, port

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}", "testserver"}
        host = headers.get("host", "")
        origin = headers.get("origin")
        if host not in hosts or (origin is not None and origin != f"http://{host}"):
            return await error_response("forbidden")(scope, receive, send)
        if scope["path"].startswith("/api/v1/") and scope["method"] not in (
            "GET",
            "HEAD",
            "OPTIONS",
        ):
            if headers.get("sec-fetch-site") == "cross-site":
                return await error_response("forbidden")(scope, receive, send)
            chunks = []
            size = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                size += len(message.get("body", b""))
                if size > self.maximum:
                    return await error_response("invalid_input", 413)(scope, receive, send)
                chunks.append(message)
                if not message.get("more_body", False):
                    break
            if size:
                if headers.get("content-type", "").split(";")[0] != "application/json":
                    return await error_response("invalid_input", 415)(scope, receive, send)
                try:
                    decode(b"".join(c.get("body", b"") for c in chunks))
                except ValueError:
                    return await error_response("invalid_input", 400)(scope, receive, send)
            original = receive

            async def replay():
                return chunks.pop(0) if chunks else await original()

            receive = replay

        async def safe_send(message):
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                    ],
                }
            await send(message)

        await self.app(scope, receive, safe_send)


def attach(app, runtime, owner):
    auth = Authority(runtime.store, owner)
    store = runtime.store
    coordinator = runtime.coordinator
    app.state.authority = auth
    from ..lifecycle.http import attach as attach_lifecycle

    attach_lifecycle(app, auth, runtime.lifecycle)
    app.add_middleware(
        Boundary, maximum=runtime.config.server.max_body_bytes, port=runtime.config.server.port
    )
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(HTTPBearer(auto_error=False))])

    @app.exception_handler(RuntimeFault)
    async def fault(_request, error):
        from ..allowances.errors import AllowanceFault

        response = error_response(error.code)
        if isinstance(error, AllowanceFault):
            # This class is raised only with static trusted accounting guidance.
            # General exceptions and all provider messages retain safe redaction.
            body = json.loads(response.body)
            body["message"] = str(error)
            return JSONResponse(body, status_code=response.status_code)
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(_request, _error):
        return error_response("invalid_input")

    @app.exception_handler(HTTPException)
    async def http_error(_request, error):
        return error_response("not_found" if error.status_code == 404 else "invalid_input", error.status_code)

    @app.exception_handler(Exception)
    async def unexpected(_request, _error):
        return error_response("internal_error")

    @router.get("/operations/diagnostics")
    def diagnostics(request: HTTPRequest):
        auth.require(request, owner=True)
        from ..operations.service import diagnostic

        return diagnostic(runtime)

    @router.get("/operations/retention")
    def retention_plan(request: HTTPRequest):
        auth.require(request, owner=True)
        from ..operations.service import retention

        return retention(runtime)

    @router.post("/auth/tokens")
    def token(request: HTTPRequest, body: Token):
        auth.require(request, owner=True)
        for key in body.adms:
            store.info(key)
        return auth.issue(adms=body.adms, permissions=body.permissions, seconds=body.expires_in)

    @router.delete("/auth/tokens/{uid}")
    def revoke(request: HTTPRequest, uid: str):
        auth.require(request, owner=True)
        auth.revoke(uid)
        return {"status": "revoked"}

    @router.get("/adms")
    def adms(request: HTTPRequest):
        principal = auth.authenticate(request)
        rows = store.list()
        if not principal["owner"]:
            rows = [r for r in rows if r["id"] in principal["adms"] and "read" in principal["permissions"]]
        return {"items": [store.info(r["id"]) for r in rows]}

    @router.post("/adms", status_code=202, response_model=Operation)
    def create(request: HTTPRequest, body: Create):
        auth.require(request, owner=True)
        return coordinator.operation("create", body.model_dump())

    @router.get("/operations/{uid}", response_model=Operation)
    def operation(request: HTTPRequest, uid: str):
        auth.require(request, owner=True)
        return coordinator.operation_info(uid)

    @router.get("/operations")
    def operations(request: HTTPRequest):
        auth.require(request, owner=True)
        with store.db() as db:
            rows = db.execute(
                "SELECT id AS operation_id,kind,adm AS adm_id,status FROM operations ORDER BY rowid DESC LIMIT 50"
            ).fetchall()
        return {"items": [dict(row) for row in rows]}

    @router.get("/adms/{adm}")
    def info(request: HTTPRequest, adm: str):
        auth.require(request, adm)
        return store.info(adm)

    @router.patch("/adms/{adm}/settings")
    def change(request: HTTPRequest, adm: str, body: Change):
        auth.require(request, adm, owner=True)
        result = store.change(adm, body.expected_epoch, mode=body.mode)
        coordinator.changed(adm)
        return result

    @router.post("/adms/{adm}/archive")
    def archive(request: HTTPRequest, adm: str, body: Epoch):
        auth.require(request, adm, owner=True)
        result = store.change(adm, body.expected_epoch, archive=True)
        coordinator.changed(adm)
        return result

    @router.get("/adms/{adm}/requirements")
    def requirements(request: HTTPRequest, adm: str):
        auth.require(request, adm)
        # Return the already admitted policy artifact without re-running semantics.
        from ..engine.data import read_json, thaw
        from ..runtime.protocol import unpack

        revision = store.revision(adm)
        package = unpack(revision["snapshot"])
        manifest = thaw(read_json(package.manifest))
        entry = next(e for e in manifest["files"] if e["role"] == "conformance")
        return {
            "policy": thaw(read_json(package.files[entry["path"]])),
            "policy_epoch": revision["context"]["policy_epoch"],
        }

    @router.get("/adms/{adm}/model")
    def model(request: HTTPRequest, adm: str, revision: str | None = None):
        auth.require(request, adm)
        from ..engine.data import read_json, thaw
        from ..runtime.protocol import unpack

        pinned = store.revision(adm, revision)
        package = unpack(pinned["snapshot"])
        manifest = thaw(read_json(package.manifest))
        artifacts = [
            {
                "digest": entry["digest"],
                "role": entry["role"],
                "value": thaw(read_json(package.files[entry["path"]])),
            }
            for entry in manifest["files"]
        ]
        return {
            "revision_id": pinned["revision_id"],
            "context": pinned["context"],
            "declarations": {
                a["value"]["symbol"]: a["value"]["declaration"]
                for a in artifacts
                if a["role"] == "declaration"
            },
            "artifacts": artifacts,
        }

    @router.put("/adms/{adm}/requirements")
    def set_requirements(request: HTTPRequest, adm: str, body: Policy):
        auth.require(request, adm, owner=True)
        rev = store.revision(adm)
        if rev["context"]["policy_epoch"] != body.expected_epoch:
            raise RuntimeFault("stale_context", "Owner epoch changed")
        prepared = runtime.supervisor.run(
            {
                "operation": "requirements",
                "snapshot": rev["snapshot"],
                "context": rev["context"],
                "policy": body.policy,
                "limits": runtime.limits(),
            }
        )
        result = store.change(adm, body.expected_epoch, prepared=prepared)
        coordinator.changed(adm)
        return result

    @router.get("/adms/{adm}/capabilities")
    def capabilities(request: HTTPRequest, adm: str):
        auth.require(request, adm)
        return runtime.query(adm, {"op": "capabilities"})["result"]

    def pagination(request):
        try:
            after = int(request.query_params.get("after", "0"))
            limit = int(request.query_params.get("limit", "50"))
            if not 0 <= after <= 9_007_199_254_740_991 or not 1 <= limit <= 100:
                raise ValueError
            return after, limit
        except ValueError:
            raise RuntimeFault("invalid_input", "Invalid pagination") from None

    @router.get("/adms/{adm}/versions")
    def versions(request: HTTPRequest, adm: str):
        auth.require(request, adm)
        return store.page(adm, "revisions", *pagination(request), descending=descending(request))

    def descending(request):
        order = request.query_params.get("order", "asc")
        if order not in ("asc", "desc"):
            raise RuntimeFault("invalid_input", "Invalid page order")
        return order == "desc"

    @router.get("/adms/{adm}/versions/{uid}")
    def version(request: HTTPRequest, adm: str, uid: str):
        auth.require(request, adm)
        return {k: v for k, v in store.revision(adm, uid).items() if k != "snapshot"}

    @router.post("/adms/{adm}/requests", status_code=202, response_model=RequestView)
    def submit(request: HTTPRequest, adm: str, body: Request):
        auth.require(request, adm, "submit")
        return coordinator.submit(adm, body.model_dump(), expected_revision=request.headers.get("if-match"))

    @router.get("/adms/{adm}/requests", response_model=RequestPage)
    def requests(request: HTTPRequest, adm: str):
        auth.require(request, adm)
        return store.page(adm, "requests", *pagination(request), descending=descending(request))

    @router.get("/adms/{adm}/requests/{uid}", response_model=RequestView)
    def result(request: HTTPRequest, adm: str, uid: str):
        auth.require(request, adm)
        return store.request(adm, uid)

    @router.post("/adms/{adm}/requests/{uid}/cancel", response_model=RequestView)
    def cancel(request: HTTPRequest, adm: str, uid: str):
        auth.require(request, adm, "submit")
        return coordinator.cancel(adm, uid)

    @router.post("/adms/{adm}/requests/{uid}/retry", status_code=202, response_model=RequestView)
    def retry(request: HTTPRequest, adm: str, uid: str):
        auth.require(request, adm, "submit")
        store.retry_request(adm, uid)
        coordinator.wake.set()
        return store.request(adm, uid)

    @router.post("/adms/{adm}/snapshot-exports", status_code=202, response_model=Operation)
    def export(request: HTTPRequest, adm: str, body: Export):
        auth.require(request, adm, owner=True)
        return coordinator.operation("export", body.model_dump(), adm=adm)

    @router.get("/adms/{adm}/events")
    async def events(request: HTTPRequest, adm: str):
        auth.require(request, adm)
        after, limit = pagination(request)
        cursor = request.headers.get("last-event-id")
        if cursor:
            try:
                prefix, number = cursor.rsplit(":", 1)
                if prefix != adm:
                    raise ValueError
                after = int(number)
                if not 0 <= after <= 9_007_199_254_740_991:
                    raise ValueError
            except ValueError:
                raise RuntimeFault("invalid_input", "Event cursor belongs to a different ADM") from None
        initial = store.events(adm, after, limit)
        if "text/event-stream" not in request.headers.get("accept", ""):
            return initial
        # Bounded connections re-open with Last-Event-ID; the outbox is authoritative.
        if not stream_slots.acquire(blocking=False):
            raise RuntimeFault("busy", "Event stream capacity occupied")

        async def stream():
            position = after
            deadline = time.monotonic() + 15
            try:
                while time.monotonic() < deadline:
                    if await request.is_disconnected():
                        break
                    try:
                        auth.require(request, adm)
                        page = store.events(adm, position, limit)
                    except RuntimeFault as error:
                        yield (
                            b"event: control\ndata: "
                            + dumps({"code": error.code, "reconnect": True})
                            + b"\n\n"
                        )
                        break
                    for event in page["items"]:
                        yield (
                            f"id: {event['event_id']}\nevent: {event['kind']}\ndata: ".encode()
                            + dumps(event)
                            + b"\n\n"
                        )
                        position = event["sequence"]
                    if not page["items"]:
                        yield b": keepalive\n\n"
                        await asyncio.sleep(0.25)
                    if request.query_params.get("once") == "true":
                        break
            finally:
                stream_slots.release()

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @router.post("/adms/{adm}/event-consumers")
    def consumer(request: HTTPRequest, adm: str, body: Cursor):
        principal = auth.require(request, adm)
        return store.consumer(adm, principal["id"], cursor=body.cursor)

    @router.put("/adms/{adm}/event-consumers/{uid}/cursor")
    def advance(request: HTTPRequest, adm: str, uid: str, body: Cursor):
        principal = auth.require(request, adm)
        return store.consumer(adm, principal["id"], uid, body.cursor)

    @router.post("/adms/{adm}/events/prune")
    def prune(request: HTTPRequest, adm: str, body: Cursor):
        auth.require(request, adm, owner=True)
        return store.prune_events(adm, body.cursor)

    @router.get("/adms/{adm}/event-window")
    def window(request: HTTPRequest, adm: str):
        auth.require(request, adm)
        store.info(adm)
        with store.db(adm) as db:
            floor = db.execute("SELECT floor FROM control WHERE id=1").fetchone()[0]
        page = store.events(adm, floor, 1)
        return {k: v for k, v in page.items() if k != "items"}

    @router.get("/openapi.json")
    def openapi(request: HTTPRequest):
        auth.require(request, owner=True)
        return app.openapi()

    import threading

    stream_slots = threading.BoundedSemaphore(32)
    from ..learning.http import public as learning_routes

    learning_routes(router, auth, runtime.learning)
    from ..language.http import public as language_routes

    language_routes(router, auth, runtime.language)
    from ..sources.http import public as source_routes

    source_routes(router, auth, runtime.sources)
    from ..feeds.http import public as feed_routes

    feed_routes(router, auth, runtime.sources)
    app.include_router(router)
    from .admin_http import attach as admin_routes

    admin_routes(app, auth, runtime)

    from ..allowances.http import attach as allowance_routes

    allowance_routes(app, auth, runtime.learning.allowances)

    from ..conversations.http import attach as conversation_routes

    conversation_routes(app, auth, runtime.conversations)
