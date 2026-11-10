"""Direct, CSRF-protected owner lifecycle controls. No provider calls."""

from typing import Literal

from fastapi import APIRouter, Request

from ..runtime.protocol import RuntimeFault
from .models import DeleteInput, RenameInput, RetryInput


def attach(app, auth, service):
    router = APIRouter(prefix="/api/v1")

    @router.patch("/adms/{adm}/name")
    def rename(request: Request, adm: str, body: RenameInput):
        auth.require(request, owner=True)
        return service.rename(adm, body.model_dump())

    @router.delete("/adms/{adm}", status_code=202)
    def delete(request: Request, adm: str, body: DeleteInput):
        auth.require(request, owner=True)
        return service.request(adm, body.model_dump())

    @router.get("/deletions")
    def listing(
        request: Request,
        after: int = 0,
        limit: int = 20,
        scope: Literal["all", "active", "completed"] = "all",
    ):
        auth.require(request, owner=True)
        if not 0 <= after <= 9007199254740991 or not 1 <= limit <= 100:
            raise RuntimeFault("invalid_input", "Invalid pagination")
        return service.listing(after, limit, scope)

    @router.get("/deletions/{operation}")
    def operation(request: Request, operation: str):
        auth.require(request, owner=True)
        return service.view(operation)

    @router.post("/deletions/{operation}/retry", status_code=202)
    def retry(request: Request, operation: str, body: RetryInput):
        auth.require(request, owner=True)
        return service.retry(operation, body.expected_version)

    app.include_router(router)
