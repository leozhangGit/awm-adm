"""Owner-only source commands; read-scoped provenance and ordinary fact queries."""

from fastapi import Query, Request

from ..learning.models import Review
from .models import BatchInput, JobInput, PolicyInput, ProjectionInput


def public(router, auth, service):
    @router.get("/adms/{adm}/sources")
    def overview(
        request: Request,
        adm: str,
        page: int = Query(0, ge=0, le=1000000),
        limit: int = Query(20, ge=1, le=50),
    ):
        auth.require(request, adm)
        return service.history(adm, page, limit)

    @router.get("/adms/{adm}/sources/history/{kind}/{identity}")
    def detail(request: Request, adm: str, kind: str, identity: str):
        auth.require(request, adm)
        return service.detail(adm, kind, identity)

    @router.post("/adms/{adm}/sources/batches", status_code=201)
    def ingest(request: Request, adm: str, body: BatchInput):
        auth.require(request, adm, owner=True)
        return service.ingest(adm, body.model_dump())

    @router.put("/adms/{adm}/sources/policy")
    def policy(request: Request, adm: str, body: PolicyInput):
        auth.require(request, adm, owner=True)
        return service.set_policy(adm, body.model_dump())

    @router.post("/adms/{adm}/sources/jobs", status_code=202)
    def extraction(request: Request, adm: str, body: JobInput):
        auth.require(request, adm, owner=True)
        return service.create_job(adm, body.model_dump())

    @router.post("/adms/{adm}/sources/episodes", status_code=202)
    def projection(request: Request, adm: str, body: ProjectionInput):
        auth.require(request, adm, owner=True)
        return service.create_projection(adm, body.model_dump())

    @router.post("/adms/{adm}/sources/episodes/{identity}/review")
    def review(request: Request, adm: str, identity: str, body: Review):
        auth.require(request, adm, owner=True)
        return service.review(adm, identity, body.model_dump())

    @router.post("/adms/{adm}/sources/jobs/{identity}/cancel")
    def cancel_job(request: Request, adm: str, identity: str):
        auth.require(request, adm, owner=True)
        return service.cancel(adm, "jobs", identity)

    @router.post("/adms/{adm}/sources/episodes/{identity}/cancel")
    def cancel_episode(request: Request, adm: str, identity: str):
        auth.require(request, adm, owner=True)
        return service.cancel(adm, "episodes", identity)
