"""Private, role-authenticated operator and component protocol."""

import secrets
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field

from ..contracts import ClosedModel
from ..engine.errors import ADMError
from ..wire import decode
from .protocol import RuntimeFault


def secret(path):
    value = Path(path).read_text().strip()
    if len(value) < 40 or len(value) > 256 or not value.isascii():
        raise ValueError("Invalid service secret")
    return value


class BodyLimit:
    def __init__(self, app, maximum):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.maximum:
                return await JSONResponse({"error": "body_too_large"}, status_code=413)(scope, receive, send)
            messages.append(message)
            if not message.get("more_body", False):
                break
        if size:
            try:
                decode(b"".join(message.get("body", b"") for message in messages))
            except ValueError:
                return await JSONResponse({"error": "invalid_json"}, status_code=400)(scope, receive, send)

        async def replay():
            return messages.pop(0) if messages else await receive()

        await self.app(scope, replay, send)


class Create(ClosedModel):
    name: str = Field(min_length=1, max_length=128)
    mode: Literal["forward", "backward"] = "backward"
    snapshot: dict | None = None


class Compute(ClosedModel):
    query: dict
    limits: dict | None = None


class ComponentLease(ClosedModel):
    role: Literal["worker", "gateway"]
    generation: str = Field(min_length=36, max_length=36)
    token: str = Field(min_length=36, max_length=36)


def create_internal(runtime, tokens):
    if len(set(tokens.values())) != 3:
        raise ValueError("Owner and component credentials must be distinct")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimit, maximum=runtime.config.server.max_body_bytes)

    @app.exception_handler(RequestValidationError)
    async def invalid_body(_request, error):
        return JSONResponse(
            {
                "error": "invalid_input",
                "fields": [{"loc": list(e["loc"]), "type": e["type"]} for e in error.errors()],
            },
            status_code=422,
        )

    def role(request: Request):
        header = request.headers.get("authorization", "")
        for name, token in tokens.items():
            if secrets.compare_digest(header, "Bearer " + token):
                return name
        raise HTTPException(401, "Authentication required")

    def owner(name=Depends(role)):
        if name != "owner":
            raise HTTPException(403, "Owner authority required")

    @app.exception_handler(RuntimeFault)
    async def fault(_request, error):
        status = {
            "not_found": 404,
            "stale_lease": 409,
            "stale_context": 409,
            "invalid_input": 422,
            "invalid_limits": 422,
            "busy": 429,
        }.get(error.code, 503)
        return JSONResponse({"error": error.code, "message": str(error)}, status_code=status)

    @app.exception_handler(ADMError)
    async def engine_error(_request, error):
        return JSONResponse({"error": error.code}, status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(_request, _error):
        return JSONResponse({"error": "storage_unavailable"}, status_code=503)

    @app.post("/internal/v3/auth/{purpose}", dependencies=[Depends(owner)])
    def auth_ticket(purpose: str):
        from ..application.admin import Administrator
        from ..application.auth import Authority

        return Administrator(Authority(runtime.store, tokens["owner"])).ticket(purpose)

    @app.get("/internal/m2/adms", dependencies=[Depends(owner)])
    def instances():
        return runtime.store.list()

    @app.post("/internal/m2/adms", dependencies=[Depends(owner)])
    def create(body: Create):
        return runtime.create(body.name, mode=body.mode, snapshot=body.snapshot)

    @app.get("/internal/m2/adms/{key}", dependencies=[Depends(owner)])
    def info(key: str):
        return runtime.store.info(key)

    @app.post("/internal/m2/adms/{key}/compute", dependencies=[Depends(owner)])
    def compute(key: str, body: Compute):
        return runtime.query(key, body.query, limits=body.limits)

    @app.get("/internal/m2/adms/{key}/runs/{run_id}", dependencies=[Depends(owner)])
    def run_info(key: str, run_id: str):
        return runtime.store.run_info(key, run_id)

    @app.post("/internal/m2/components/claim")
    def claim(name=Depends(role)):
        if name == "owner":
            raise HTTPException(403, "Component credential required")
        return runtime.store.component_claim(name)

    @app.post("/internal/m2/components/renew")
    def renew(lease: ComponentLease, name=Depends(role)):
        if lease.role != name:
            raise HTTPException(403, "Wrong component scope")
        return runtime.store.component_renew(lease.model_dump())

    @app.get("/internal/m2/work")
    def work(name=Depends(role)):
        if name != "worker":
            raise HTTPException(403, "Worker credential required")
        return {"state": "idle", "job": None, "reason": "use_m5_claim", "learning_implemented": True}

    from ..learning.http import private as learning_routes

    learning_routes(app, role, runtime.learning)
    return app
