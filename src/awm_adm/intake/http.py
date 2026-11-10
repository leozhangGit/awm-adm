"""Owner uploads and strictly append-only connector boundary."""

from fastapi import APIRouter, Request

from .models import AppendCredential, AppendInput, Upload


def attach(app, auth, service):
    router = APIRouter(prefix="/api/v1/adms/{adm}")

    @router.get("/attachments")
    def listing(request: Request, adm: str):
        auth.require(request, adm, owner=True)
        return service.attachments(adm)

    @router.post("/attachments", status_code=201)
    def upload(request: Request, adm: str, body: Upload):
        auth.require(request, adm, owner=True)
        return service.upload(adm, body.model_dump())

    @router.post("/intake/{uid}/credentials", status_code=201)
    def credential(request: Request, adm: str, uid: str, body: AppendCredential):
        auth.require(request, adm, owner=True)
        return service.issue(adm, uid, body.model_dump(), auth)

    @router.post("/intake/{uid}/push", status_code=202)
    def push(request: Request, adm: str, uid: str, body: AppendInput):
        principal = auth.require(request, adm, permission="append")
        return service.push(adm, uid, body.model_dump(), principal)

    @router.get("/intake/{uid}/receipts/{identity}")
    def receipt(request: Request, adm: str, uid: str, identity: str):
        principal = auth.require(request, adm, permission="append")
        return service.receipt(adm, uid, identity, principal)

    app.include_router(router)
