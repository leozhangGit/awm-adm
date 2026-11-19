"""Owner-only conversation boundary; preview consent is never reused."""

from typing import Literal

from fastapi import APIRouter, Query, Request


def attach(app, auth, service):
    router = APIRouter(prefix="/api/v1")

    @router.get("/adms/{adm}/conversations")
    def listing(
        request: Request,
        adm: str,
        channel: Literal["ask", "teach"],
        after: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
    ):
        auth.require(request, adm, owner=True)
        return service.listing(adm, channel, after, limit)

    @router.get("/adms/{adm}/history-options")
    def history_options(request: Request, adm: str):
        auth.require(request, adm)
        from .history import options

        return options(service, adm)

    @router.get("/adms/{adm}/conversations/{cid}")
    def detail(
        request: Request,
        adm: str,
        cid: str,
        after: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
    ):
        auth.require(request, adm, owner=True)
        return service.get(adm, cid, after, limit)

    @router.get("/adms/{adm}/conversations/{cid}/details")
    def technical(request: Request, adm: str, cid: str):
        auth.require(request, adm, owner=True)
        return service.details(adm, cid)

    @router.get("/adms/{adm}/presentations/{uid}")
    def presentation(request: Request, adm: str, uid: str):
        auth.require(request, adm, owner=True)
        return service.ask.get(adm, uid)

    @router.get("/adms/{adm}/tasks")
    def tasks(request: Request, adm: str, after: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
        auth.require(request, adm, owner=True)
        return service.teaching.listing(adm, after, limit)

    @router.get("/adms/{adm}/tasks/{uid}")
    def task(request: Request, adm: str, uid: str):
        auth.require(request, adm, owner=True)
        return service.teaching.get(adm, uid)

    from ..teaching.execution_models import TaskCommand

    @router.post("/adms/{adm}/tasks/{uid}/commands")
    def task_command(request: Request, adm: str, uid: str, body: TaskCommand):
        principal = auth.require(request, adm, owner=True)
        return service.teaching.execution.command(adm, uid, body.model_dump(), principal["id"])

    app.include_router(router)
    from ..intake.http import attach as attach_intake

    attach_intake(app, auth, service.intake)
