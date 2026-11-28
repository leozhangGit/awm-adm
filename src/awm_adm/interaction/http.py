"""Direct connection controls; no financial or purpose setup endpoints."""

from typing import Literal

from fastapi import Header, Query, Request

from .models import DirectMessage, DirectTeach, DisableConnection, EnableConnection


def attach(router, auth, runtime):
    service = runtime.learning.connection_manager

    @router.get("/connection")
    def connection(request: Request):
        auth.require(request, owner=True)
        return service.view()

    @router.post("/connection/enable", status_code=202)
    def enable(request: Request, body: EnableConnection):
        auth.require(request, owner=True)
        return service.enable(body.model_dump())

    @router.post("/connection/disable")
    def disable(request: Request, body: DisableConnection):
        auth.require(request, owner=True)
        return service.disable(body.model_dump())

    @router.get("/connection/operations/{operation}")
    def operation(request: Request, operation: str):
        auth.require(request, owner=True)
        return service.operation(operation)

    @router.get("/connection/usage")
    def usage(request: Request, timezone: str = Query(default="UTC", max_length=128)):
        auth.require(request, owner=True)
        return service.usage(timezone)

    @router.post("/adms/{adm}/ask", status_code=202)
    def ask(
        request: Request,
        adm: str,
        body: DirectMessage,
        if_match: str | None = Header(default=None, max_length=128),
    ):
        auth.require(request, adm, owner=True)
        return runtime.interactions.submit(
            adm,
            "ask",
            body.model_dump(),
            origin="console" if request.headers.get("x-adm-client") == "console" else "api",
            expected_revision=if_match,
        )

    @router.post("/adms/{adm}/teach", status_code=202)
    def teach(
        request: Request,
        adm: str,
        body: DirectTeach,
        if_match: str | None = Header(default=None, max_length=128),
    ):
        auth.require(request, adm, owner=True)
        return runtime.interactions.submit(
            adm,
            "teach",
            body.model_dump(),
            origin="console" if request.headers.get("x-adm-client") == "console" else "api",
            expected_revision=if_match,
        )

    @router.post("/adms/{adm}/source-queues", status_code=202)
    def source_queue(request: Request, adm: str, body: DirectMessage):
        auth.require(request, adm, owner=True)
        return runtime.interactions.submit(adm, "teach", body.model_dump(), source_queue=True)

    @router.get("/adms/{adm}/chat/{channel}")
    def chat(
        request: Request,
        adm: str,
        channel: Literal["ask", "teach"],
        after: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
        direction: Literal["forward", "backward"] = "forward",
        before: int | None = Query(None, ge=1),
    ):
        auth.require(request, adm, owner=True)
        return runtime.interactions.chat(
            adm, channel, after=after, limit=limit, direction=direction, before=before
        )

    @router.get("/adms/{adm}/interactions/{interaction}")
    def interaction(request: Request, adm: str, interaction: str):
        auth.require(request, adm, owner=True)
        return runtime.interactions.get(adm, interaction)

    @router.post("/adms/{adm}/interactions/{interaction}/cancel")
    def cancel(request: Request, adm: str, interaction: str):
        principal = auth.require(request, adm, owner=True)
        return runtime.interactions.cancel(adm, interaction, principal["id"])

    @router.get("/adms/{adm}/activity")
    def activity(
        request: Request,
        adm: str,
        kind: Literal[
            "ask", "teach", "request", "learning", "extraction", "source_admission", "source_intake"
        ]
        | None = None,
        origin: Literal["api", "console", "legacy_chat"] | None = None,
        start: int | None = Query(None, ge=0),
        end: int | None = Query(None, ge=0),
        after: str | None = Query(None, max_length=4096),
        limit: int = Query(20, ge=1, le=100),
    ):
        auth.require(request, adm, owner=True)
        from .activity import history

        return history(runtime, adm, start=start, end=end, after=after, limit=limit, kind=kind, origin=origin)

    @router.get("/adms/{adm}/knowledge")
    def knowledge(
        request: Request,
        adm: str,
        query: str = Query("", max_length=256),
        kind: str | None = Query(None, max_length=40),
        after: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
        revision: str | None = Query(None, max_length=128),
    ):
        auth.require(request, adm)
        from .knowledge import search

        return search(runtime, adm, query=query, kind=kind, after=after, limit=limit, revision=revision)
