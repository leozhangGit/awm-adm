"""Owner-only financial controls. These endpoints do not dispatch calls."""

from fastapi import APIRouter, Query, Request


def attach(app, auth, service):
    router = APIRouter(prefix="/api/v1")

    @router.get("/spending")
    def settings(request: Request):
        auth.require(request, owner=True)
        return service.settings()

    @router.get("/prices")
    def prices(
        request: Request, after: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)
    ):
        auth.require(request, owner=True)
        return service.listing("prices", after, limit)

    @router.get("/allowances")
    def allowances(
        request: Request, after: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)
    ):
        auth.require(request, owner=True)
        return service.listing("allowances", after, limit)

    @router.get("/allowances/{key}")
    def detail(request: Request, key: str):
        auth.require(request, owner=True)
        return service.view(key)

    app.include_router(router)
