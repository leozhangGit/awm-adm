"""Owner-only financial controls. These endpoints do not dispatch calls."""

from fastapi import APIRouter, Query, Request

from .models import AllowanceInput, CloseInput, PriceInput, SpendingInput


def attach(app, auth, service):
    router = APIRouter(prefix="/api/v1")

    @router.get("/spending")
    def settings(request: Request):
        auth.require(request, owner=True)
        return service.settings()

    @router.put("/spending")
    def configure(request: Request, body: SpendingInput):
        auth.require(request, owner=True)
        return service.configure(body.model_dump())

    @router.get("/prices")
    def prices(
        request: Request, after: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)
    ):
        auth.require(request, owner=True)
        return service.listing("prices", after, limit)

    @router.post("/prices", status_code=201)
    def price(request: Request, body: PriceInput):
        auth.require(request, owner=True)
        return service.save_price(body.model_dump())

    @router.get("/connections/{key}/price-options")
    def price_options(request: Request, key: str):
        auth.require(request, owner=True)
        return service.price_options(key)

    @router.get("/allowances")
    def allowances(
        request: Request, after: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)
    ):
        auth.require(request, owner=True)
        return service.listing("allowances", after, limit)

    @router.post("/allowances", status_code=201)
    def create(request: Request, body: AllowanceInput):
        auth.require(request, owner=True)
        return service.create(body.model_dump())

    @router.get("/allowances/{key}")
    def detail(request: Request, key: str):
        auth.require(request, owner=True)
        return service.view(key)

    @router.post("/allowances/{key}/close")
    def close(request: Request, key: str, body: CloseInput):
        auth.require(request, owner=True)
        return service.close(key, body.expected_state)

    app.include_router(router)
