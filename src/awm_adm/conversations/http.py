"""Owner-only conversation boundary; preview consent is never reused."""

from typing import Literal

from fastapi import APIRouter, Query, Request

from .models import (
    ConversationInput,
    DecisionInput,
    GapInput,
    LinkInput,
    MessageInput,
    SetupInput,
)


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

    @router.post("/adms/{adm}/conversations", status_code=201)
    def create(request: Request, adm: str, body: ConversationInput):
        auth.require(request, adm, owner=True)
        return service.create(adm, body.model_dump())

    @router.get("/adms/{adm}/interaction-options")
    def options(
        request: Request, adm: str, purpose: Literal["clarification", "ask", "teach"] = "clarification"
    ):
        auth.require(request, adm, owner=True)
        return service.options(adm, purpose)

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

    @router.post("/adms/{adm}/conversations/{cid}/setup", status_code=201)
    def setup(request: Request, adm: str, cid: str, body: SetupInput):
        auth.require(request, adm, owner=True)
        return service.setup(adm, cid, body.model_dump())

    @router.post("/adms/{adm}/conversations/{cid}/messages", status_code=202)
    def message(request: Request, adm: str, cid: str, body: MessageInput):
        auth.require(request, adm, owner=True)
        return service.message(adm, cid, body.model_dump())

    @router.post("/adms/{adm}/decisions/{uid}")
    def decide(request: Request, adm: str, uid: str, body: DecisionInput):
        principal = auth.require(request, adm, owner=True)
        return service.decide(adm, uid, body.model_dump(), principal["id"])

    @router.post("/adms/{adm}/conversations/{cid}/links", status_code=201)
    def link(request: Request, adm: str, cid: str, body: LinkInput):
        auth.require(request, adm, owner=True)
        return service.link(adm, cid, body.model_dump())

    @router.get("/adms/{adm}/presentations/{uid}")
    def presentation(request: Request, adm: str, uid: str):
        auth.require(request, adm, owner=True)
        return service.ask.get(adm, uid)

    @router.post("/adms/{adm}/ask/{uid}/teach", status_code=201)
    def gap(request: Request, adm: str, uid: str, body: GapInput):
        auth.require(request, adm, owner=True)
        return service.ask.gap(adm, uid, body.model_dump())

    @router.get("/adms/{adm}/tasks")
    def tasks(request: Request, adm: str, after: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
        auth.require(request, adm, owner=True)
        return service.teaching.listing(adm, after, limit)

    @router.get("/adms/{adm}/tasks/{uid}")
    def task(request: Request, adm: str, uid: str):
        auth.require(request, adm, owner=True)
        return service.teaching.get(adm, uid)

    from ..teaching.execution_models import TaskCommand
    from ..teaching.renewal import RenewalInput

    @router.get("/adms/{adm}/tasks/{uid}/renewal")
    def renewal_options(request: Request, adm: str, uid: str):
        auth.require(request, adm, owner=True)
        return service.teaching.renewal.preview(adm, uid)

    @router.post("/adms/{adm}/tasks/{uid}/renewal")
    def renewal_confirm(request: Request, adm: str, uid: str, body: RenewalInput):
        principal = auth.require(request, adm, owner=True)
        return service.teaching.renewal.confirm(adm, uid, body.model_dump(), principal["id"])

    @router.post("/adms/{adm}/tasks/{uid}/commands")
    def task_command(request: Request, adm: str, uid: str, body: TaskCommand):
        principal = auth.require(request, adm, owner=True)
        return service.teaching.execution.command(adm, uid, body.model_dump(), principal["id"])

    app.include_router(router)
    from ..intake.http import attach as attach_intake

    attach_intake(app, auth, service.intake)
