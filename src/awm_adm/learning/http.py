"""Owner learning controls and distinct worker/gateway endpoints."""

from fastapi import Depends, HTTPException, Request
from pydantic import Field

from ..contracts import ClosedModel
from .models import (
    ConnectionChange,
    ConnectionInput,
    EpisodeInput,
    LearningSettings,
    Outcome,
    Review,
    TestConnection,
)


class Sync(ClosedModel):
    public_key: dict
    acknowledgments: list[dict] = Field(default_factory=list, max_length=20)
    deletion_acknowledgments: list[str] = Field(default_factory=list, max_length=100)


class Dispatch(ClosedModel):
    grant_id: str = Field(max_length=100)
    lease: str = Field(max_length=100)


class Delivery(Dispatch):
    outcome: Outcome


def public(router, auth, service):
    @router.get("/learning")
    def settings(request: Request):
        auth.require(request, owner=True)
        return {**service.settings(), "usage": service.usage()}

    @router.put("/learning")
    def configure(request: Request, body: LearningSettings):
        auth.require(request, owner=True)
        return service.configure(body.model_dump())

    @router.get("/connections")
    def connections(request: Request):
        auth.require(request, owner=True)
        return {"items": service.connections()}

    @router.get("/connections/{connection}")
    def connection_detail(request: Request, connection: str):
        auth.require(request, owner=True)
        value = service.connection(connection, private=True)
        value.pop("sealed_credential", None)
        value.pop("sealing_key_id", None)
        return value

    @router.post("/connections", status_code=202)
    def create_connection(request: Request, body: ConnectionInput):
        auth.require(request, owner=True)
        return service.save_connection(body.model_dump())

    @router.put("/connections/{connection}", status_code=202)
    def change_connection(request: Request, connection: str, body: ConnectionChange):
        auth.require(request, owner=True)
        return service.save_connection(body.model_dump(), connection)

    @router.post("/connections/{connection}/test", status_code=202)
    def test_connection(request: Request, connection: str, body: TestConnection):
        auth.require(request, owner=True)
        return service.test_connection(connection, body.model_dump())

    @router.get("/dispatches/{grant}")
    def dispatch(request: Request, grant: str):
        auth.require(request, owner=True)
        return service.grant_view(grant)

    @router.get("/adms/{adm}/episodes")
    def episodes(request: Request, adm: str):
        auth.require(request, adm, owner=True)
        return {"items": service.episodes(adm)}

    @router.post("/adms/{adm}/episodes", status_code=202)
    def create_episode(request: Request, adm: str, body: EpisodeInput):
        auth.require(request, adm, owner=True)
        return service.create(adm, body.model_dump())

    @router.get("/adms/{adm}/episodes/{episode}")
    def episode(request: Request, adm: str, episode: str):
        auth.require(request, adm, owner=True)
        return service.episode(adm, episode)

    @router.post("/adms/{adm}/episodes/{episode}/cancel")
    def cancel(request: Request, adm: str, episode: str):
        auth.require(request, adm, owner=True)
        return service.cancel(adm, episode)

    @router.post("/adms/{adm}/candidates/{candidate}/review")
    def review(request: Request, adm: str, candidate: str, body: Review):
        auth.require(request, adm, owner=True)
        return service.review(adm, candidate, body.model_dump())


def private(app, role, service):
    def worker(name=Depends(role)):
        if name != "worker":
            raise HTTPException(403, "Worker authority required")

    def gateway(name=Depends(role)):
        if name != "gateway":
            raise HTTPException(403, "Gateway authority required")

    @app.post("/internal/m5/claim", dependencies=[Depends(worker)])
    def claim():
        return {"job": service.claim()}

    @app.post("/internal/m5/synchronize", dependencies=[Depends(gateway)])
    def synchronize(body: Sync):
        return service.synchronize(body.public_key, body.acknowledgments, body.deletion_acknowledgments)

    @app.post("/internal/m5/authorize", dependencies=[Depends(gateway)])
    def authorize(body: Dispatch):
        return service.authorize(body.grant_id, body.lease)

    @app.post("/internal/m5/outcome", dependencies=[Depends(gateway)])
    def outcome(body: Delivery):
        return service.outcome(body.grant_id, body.lease, body.outcome.model_dump())
