"""Small project workflow over the public service API; no service internals."""

import os
import time
from pathlib import Path
from uuid import uuid4

from .client import Client, Problem, identifier
from .journal import Journal
from .project import project_context


class Connector:
    def __init__(self, client=None, journal=None):
        self.client = client or Client(os.environ.get("AWM_ADM_URL", "http://127.0.0.1:9527"))
        self.journal = journal or Journal(Path.home() / ".local/share/awm-adm-codex")

    def checked_service(self, state):
        service = self.client.system()
        expected = state["binding"] or state["creation"]
        if expected and (
            expected["origin"] != self.client.origin
            or expected["installation_id"] != service["installation_id"]
        ):
            raise Problem(
                "installation_changed",
                "The service target or installation changed. Explicitly select a model before rebinding; existing work is preserved.",
            )
        return service

    def bound(self, state):
        if not state["binding"]:
            raise Problem("not_bound", "Use AWM-ADM for this project first to create or select its model.")
        key = state["binding"]["model_id"]
        model = self.client.model(key)
        if model.get("id") != key or model.get("status") != "ready" or model.get("archived"):
            raise Problem(
                "model_unavailable",
                "The bound model is not available for project work. Review it in the console.",
            )
        identifier(model.get("revision_id"))
        return model

    @staticmethod
    def view(model):
        return {
            k: model.get(k)
            for k in ("id", "name", "mode", "revision_id", "policy_epoch", "theory_version", "support_root")
        }

    def status(self, project_root, workspace_roots=None):
        project = project_context(project_root, workspace_roots)
        if project["state"] != "project_selected":
            return project
        with self.journal.project(project["project_root"]) as (state, save):
            service = self.checked_service(state)
            if not state["binding"]:
                return {
                    "state": "unbound",
                    "summary": "The local service is ready. This project has no model binding yet.",
                    "project": project,
                    "service": service,
                    "creation_pending": state["creation"] is not None,
                }
            model = self.bound(state)
            return {
                "state": "ready",
                "summary": "Project model connected.",
                "project": project,
                "service": service,
                "model": self.view(model),
                "work": [
                    {"work_id": k, "kind": v["kind"], "status": v.get("status", "pending")}
                    for k, v in list(state["work"].items())[-20:]
                ],
                "work_count": len(state["work"]),
            }

    def project(self, project_root, *, model_id=None, workspace_roots=None):
        project = project_context(project_root, workspace_roots)
        if project["state"] != "project_selected":
            return project
        with self.journal.project(project["project_root"]) as (state, save):
            if model_id is not None:
                # An explicit target is required; never search or match names.
                service = self.client.system()
                model = self.client.model(identifier(model_id))
                if model.get("id") != model_id or model.get("status") != "ready" or model.get("archived"):
                    raise Problem("model_unavailable", "Select an active ready model.")
                if state["creation"]:
                    raise Problem(
                        "creation_pending", "Recover the pending creation before changing the binding."
                    )
                if (
                    (state["work"] or state.get("mode_operations"))
                    and state["binding"]
                    and (
                        state["binding"]["model_id"] != model_id
                        or state["binding"]["origin"] != self.client.origin
                        or state["binding"]["installation_id"] != service["installation_id"]
                    )
                ):
                    raise Problem(
                        "work_retained",
                        "This binding has retained work. Preserve/archive its journal before selecting another model.",
                    )
                identifier(model.get("revision_id"))
                state["binding"] = {
                    "origin": self.client.origin,
                    "installation_id": service["installation_id"],
                    "model_id": model_id,
                }
                save()
            else:
                service = self.checked_service(state)
                if state["binding"]:
                    model = self.bound(state)
                else:
                    if not state["creation"]:
                        state["creation"] = {
                            "origin": self.client.origin,
                            "installation_id": service["installation_id"],
                            "idempotency_key": "project-" + str(uuid4()),
                            "name": project["project_name"][:128],
                            "operation_id": None,
                        }
                        save()
                    intent = state["creation"]
                    if not intent["operation_id"]:
                        operation = self.client.create(intent["name"], intent["idempotency_key"])
                        intent["operation_id"] = identifier(operation["operation_id"])
                        save()
                    deadline = time.monotonic() + 2
                    while True:
                        operation = self.client.operation(intent["operation_id"])
                        if operation.get("status") == "succeeded":
                            key = identifier(operation["result"]["adm_id"])
                            model = self.client.model(key)
                            if (
                                model.get("id") != key
                                or model.get("status") != "ready"
                                or model.get("archived")
                            ):
                                raise Problem(
                                    "model_unavailable",
                                    "The created model is not ready; its operation is retained.",
                                )
                            identifier(model.get("revision_id"))
                            state["binding"] = {
                                "origin": self.client.origin,
                                "installation_id": service["installation_id"],
                                "model_id": key,
                            }
                            state["creation"] = None
                            save()
                            break
                        if operation.get("status") not in {"received", "running"}:
                            raise Problem(
                                "creation_failed",
                                "Model creation did not complete. Its original operation is retained for inspection; it has not been retried as new work.",
                            )
                        if time.monotonic() >= deadline:
                            return {
                                "state": "creating",
                                "summary": "The model is still being created. Check this same project again to resume.",
                                "operation_id": intent["operation_id"],
                            }
                        time.sleep(0.1)
            return {
                "state": "ready",
                "summary": "Project model connected. Its current conflict mode is preserved.",
                "project": project,
                "service": service,
                "model": self.view(model),
            }

    def ask(self, project_root, **kwargs):
        from .work import submit

        return submit(self, project_root, "ask", **kwargs)

    def teach(self, project_root, **kwargs):
        from .work import submit

        return submit(self, project_root, "teach", **kwargs)

    def work(self, project_root, **kwargs):
        from .work import work

        return work(self, project_root, **kwargs)

    def set_mode(self, project_root, **kwargs):
        from .mode import set_mode

        return set_mode(self, project_root, **kwargs)
