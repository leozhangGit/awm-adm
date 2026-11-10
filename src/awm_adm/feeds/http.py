"""Standing policy mutations are owner-only; progress has instance read scope."""

from fastapi import Query, Request

from .models import CoverageInput, FeedControl, FeedInput, Reprocess


def public(router, auth, sources):
    feeds = sources.feeds

    @router.get("/adms/{adm}/feeds")
    def overview(
        request: Request,
        adm: str,
        after: int = Query(0, ge=0, le=9007199254740991),
        limit: int = Query(50, ge=1, le=100),
    ):
        auth.require(request, adm)
        return feeds.overview(adm, after, limit)

    @router.post("/adms/{adm}/feeds", status_code=201)
    def create(request: Request, adm: str, body: FeedInput):
        auth.require(request, adm, owner=True)
        return feeds.create(adm, body.model_dump())

    @router.put("/adms/{adm}/feeds/{identity}")
    def control(request: Request, adm: str, identity: str, body: FeedControl):
        auth.require(request, adm, owner=True)
        return feeds.control(adm, identity, body.model_dump())

    @router.post("/adms/{adm}/feeds/{identity}/reprocess", status_code=202)
    def reprocess(request: Request, adm: str, identity: str, body: Reprocess):
        auth.require(request, adm, owner=True)
        return feeds.reprocess(adm, identity, body.model_dump())

    @router.post("/adms/{adm}/sources/coverage")
    def coverage(request: Request, adm: str, body: CoverageInput):
        auth.require(request, adm, owner=True)
        return sources.coverage(adm, body.model_dump())
