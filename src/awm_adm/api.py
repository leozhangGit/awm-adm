"""Public local console assets, readiness and login-free application resources."""

from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import AppConfig
from .contracts import ClosedModel, RequestLimits


class LocalServiceInfo(ClosedModel):
    profile: Literal["awm-adm-local/1"] = "awm-adm-local/1"
    installation_id: str
    connection_ready: bool
    reason: Literal["ready", "connection_disabled", "connection_not_ready"]


class SystemInfo(ClosedModel):
    product: str
    version: str
    stage: str
    operational: bool
    implemented: list[str]
    available: dict
    request_limits: RequestLimits
    local_service: LocalServiceInfo | None = None


def system_info(runtime=None):
    return {
        "product": "awm-adm",
        "version": __version__,
        "stage": "release",
        "operational": runtime is not None,
        "implemented": [
            "configuration_validation",
            "boundary_schemas",
            "finite_engine_library",
            "ordered_memory_admission",
            "owner_conformance",
            "model_snapshots",
            "invariant_certificates",
            "persistent_instance_lifecycle",
            "durable_model_deletion",
            "owner_model_naming",
            "supervised_local_compute",
            "durable_local_requests",
            "transactional_events",
            "login_free_local_workspace",
            "reserved_interaction_capacity",
            "durable_ask_teach_workspace",
            "exact_conversation_decisions",
            "checked_teaching_preparation",
            "credential_gateway",
            "bounded_learning_episodes",
            "source_ingestion",
            "continuous_source_feeds",
            "explicit_coverage_transitions",
            "offline_service_backup_restore",
            "bounded_owner_diagnostics",
            "explicit_retention_preview",
            "historical_fact_projection",
            "typed_interpretations",
            "bounded_conversations",
            "durable_ordered_admission",
        ],
        "available": runtime.status()
        if runtime
        else {"local_serving": False, "learning": False, "providers": False, "lean": False},
    }


def create_app(config: AppConfig | None = None, *, runtime=None, assets=None, ingress=()) -> FastAPI:
    app = FastAPI(
        title="AWM-ADM local API", version=__version__, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.config = config or AppConfig()

    @app.get("/health/live")
    def live():
        return {"status": "live", "stage": "release"}

    @app.get("/health/ready")
    def ready():
        if runtime:
            status = runtime.status()
            return JSONResponse(
                status_code=200 if status["local_serving"] else 503,
                content={"status": "ready" if status["local_serving"] else "not_ready", "components": status},
            )
        return JSONResponse(
            status_code=503, content={"status": "not_ready", "reason": "development_status_only"}
        )

    @app.get("/api/v1/system", response_model=SystemInfo)
    def system():
        result = system_info(runtime)
        result["request_limits"] = app.state.config.request.model_dump()
        if runtime:
            from .application.local_access import LocalWorkspace
            from .runtime.protocol import RuntimeFault

            reason = "ready"
            try:
                runtime.learning.connection_manager.active("ask_interpretation")
                runtime.learning.connection_manager.active("task_preparation")
            except RuntimeFault:
                reason = (
                    "connection_disabled"
                    if runtime.learning.connection_manager.control()["state"] == "disabled"
                    else "connection_not_ready"
                )
            result["local_service"] = {
                "profile": "awm-adm-local/1",
                "installation_id": LocalWorkspace(runtime.store).identity,
                "connection_ready": reason == "ready",
                "reason": reason,
            }
        return result

    if runtime is not None:
        from .application.http import attach

        attach(app, runtime, ingress=ingress)
    if assets is not None:
        app.mount("/", StaticFiles(directory=assets, html=True), name="console")

    return app
