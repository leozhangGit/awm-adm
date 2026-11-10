"""Public local console assets, readiness and authenticated application resources."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import AppConfig


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
            "owner_and_scoped_client_authentication",
            "local_administrator_password_and_recovery",
            "priced_purpose_allowances",
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


def create_app(config: AppConfig | None = None, *, runtime=None, assets=None, owner_token=None) -> FastAPI:
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

    @app.get("/api/v1/system")
    def system():
        return system_info(runtime)

    if runtime is not None and owner_token is not None:
        from .application.http import attach

        attach(app, runtime, owner_token)
    if assets is not None:
        app.mount("/", StaticFiles(directory=assets, html=True), name="console")

    return app
