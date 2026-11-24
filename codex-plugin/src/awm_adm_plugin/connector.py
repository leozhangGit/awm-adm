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
                creation = state["creation"]
                operation = (
                    self.client.operation(creation["operation_id"])
                    if creation and creation["operation_id"]
                    else None
                )
                return {
                    **self.creation_view(operation),
                    "project": project,
                    "service": service,
                    "creation_pending": bool(creation)
                    and (operation is None or operation.get("status") in {"received", "running"}),
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

    @staticmethod
    def creation_view(operation):
        value = {
            "state": "unbound",
            "summary": "The local service is ready. This project has no model binding yet.",
        }
        if operation is None:
            return value
        value["creation"] = operation
        if operation.get("status") == "failed":
            reason = (operation.get("error") or {}).get("details", {}).get("reason")
            value.update(
                state="creation_failed",
                summary=(
                    "The model limit was reached. Free a slot, then request a new creation attempt."
                    if reason == "model_limit_reached"
                    else "The retained model creation failed. It is not pending and has not been retried."
                ),
                retry_new_creation=operation.get("retry_new_creation") is True,
            )
        return value

    def project(self, project_root, *, model_id=None, retry_creation=None, workspace_roots=None):
        project = project_context(project_root, workspace_roots)
        if project["state"] != "project_selected":
            return project
        if retry_creation is not None:
            identifier(retry_creation)
            if model_id is not None:
                raise Problem("invalid_input", "Choose either an existing model or a new creation attempt.")
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
                    if retry_creation is not None:
                        intent = state["creation"]
                        if not intent:
                            raise Problem("creation_changed", "There is no retained creation to retry.")
                        # Repeated recovery of this decision resumes its one new
                        # intent, including after a lost acknowledgement.
                        if intent.get("retry_of") != retry_creation:
                            if intent["operation_id"] != retry_creation:
                                raise Problem(
                                    "creation_changed",
                                    "The retained creation changed. Check its current status.",
                                )
                            failed = self.client.operation(retry_creation)
                            if not (
                                failed.get("status") == "failed"
                                and failed.get("kind") == "create"
                                and failed.get("adm_id") is None
                                and failed.get("retry_new_creation") is True
                            ):
                                raise Problem(
                                    "creation_unresolved",
                                    "The service has not confirmed a failed creation without an allocated model. Recover the original operation first.",
                                )
                            state.setdefault("creation_history", []).append(
                                {"intent": dict(intent), "outcome": failed}
                            )
                            state["creation"] = None
                    if not state["creation"]:
                        state["creation"] = {
                            "origin": self.client.origin,
                            "installation_id": service["installation_id"],
                            "idempotency_key": "project-" + str(uuid4()),
                            "name": project["project_name"][:128],
                            "operation_id": None,
                            "retry_of": retry_creation,
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
                            return self.creation_view(operation)
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
