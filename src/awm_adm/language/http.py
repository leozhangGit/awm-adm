"""Manual interpretation previews; interpretation data never grants owner authority."""

from fastapi import Request

from ..contracts import ClosedModel, Identifier
from .models import ConversationInput, ExecuteInput, InterpretationInput, TeachInput, VocabularyInput


class Revalidate(ClosedModel):
    idempotency_key: Identifier
    expected_revision: Identifier


def public(router, auth, service):
    @router.get("/adms/{adm}/language/catalog")
    def catalog(request: Request, adm: str):
        auth.require(request, adm)
        return service.catalog(adm)

    @router.get("/adms/{adm}/language/vocabulary")
    def vocabulary(request: Request, adm: str):
        auth.require(request, adm)
        return service.vocabulary(adm)

    @router.put("/adms/{adm}/language/vocabulary")
    def change_vocabulary(request: Request, adm: str, body: VocabularyInput):
        auth.require(request, adm, owner=True)
        return service.set_vocabulary(adm, body.model_dump())

    @router.get("/adms/{adm}/interpretation-sessions")
    def conversations(request: Request, adm: str):
        auth.require(request, adm)
        return {"items": service.conversations(adm)}

    @router.post("/adms/{adm}/interpretation-sessions", status_code=201)
    def create_conversation(request: Request, adm: str, body: ConversationInput):
        auth.require(request, adm, "submit")
        return service.create_conversation(adm, body.model_dump())

    @router.get("/adms/{adm}/interpretation-sessions/{conversation}")
    def conversation_detail(request: Request, adm: str, conversation: str):
        auth.require(request, adm)
        return service.conversation(adm, conversation)

    @router.post("/adms/{adm}/interpretation-sessions/{conversation}/teach", status_code=201)
    def teach(request: Request, adm: str, conversation: str, body: TeachInput):
        auth.require(request, adm, owner=True)
        return service.teach(adm, conversation, body.model_dump())

    @router.post("/adms/{adm}/interpretations", status_code=202)
    def interpret(request: Request, adm: str, body: InterpretationInput):
        auth.require(request, adm, "submit", owner=body.translator == "external")
        return service.create(adm, body.model_dump())

    @router.get("/adms/{adm}/interpretations/{interpretation}")
    def interpretation_detail(request: Request, adm: str, interpretation: str):
        auth.require(request, adm)
        return service.get(adm, interpretation)

    @router.post("/adms/{adm}/interpretations/{interpretation}/clarify", status_code=202)
    def clarify(request: Request, adm: str, interpretation: str, body: InterpretationInput):
        auth.require(request, adm, "submit", owner=body.translator == "external")
        return service.create(adm, body.model_dump(), parent=interpretation)

    @router.post("/adms/{adm}/interpretations/{interpretation}/revalidate", status_code=202)
    def revalidate(request: Request, adm: str, interpretation: str, body: Revalidate):
        auth.require(request, adm, "submit")
        return service.revalidate(adm, interpretation, body.model_dump())

    @router.post("/adms/{adm}/interpretations/{interpretation}/execute", status_code=202)
    def execute(request: Request, adm: str, interpretation: str, body: ExecuteInput):
        auth.require(request, adm, "submit")
        return service.execute(adm, interpretation, body.model_dump())

    @router.post("/adms/{adm}/interpretations/{interpretation}/cancel")
    def cancel(request: Request, adm: str, interpretation: str):
        auth.require(request, adm, "submit")
        return service.cancel(adm, interpretation)
