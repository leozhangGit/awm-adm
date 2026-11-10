"""Single-process ADM ownership and ordered admission for the finite library.

Immutable models and short locked publication preserve concurrent serving.
This is an in-memory coordination core, not the durable application runtime.
"""

from threading import RLock
from uuid import uuid4

from .admission import reconcile
from .artifacts import digest
from .budget import Budget
from .candidates import unpack
from .conformance import EMPTY_POLICY, validate_policy, verify_policy
from .data import encode, read_json, thaw
from .errors import ADMError, Conflict, InvalidIR, NotFound, Rejected, ResourceLimit, StorageError
from .execution import execute, normalize_query
from .model import admit
from .results import semantic_query

TERMINAL = {"accepted", "rejected", "inconclusive"}
DEFAULT_LIMITS = {
    "max_work": 1_000_000,
    "max_duration_ms": 10_000,
    "max_states": 10_000,
    "max_search_bytes": 16_000_000,
}


def _copy(value):
    return thaw(read_json(encode(value)))


class Instance:
    """Owner-facing local library. Provider workers never receive this handle."""

    def __init__(
        self,
        model_document=None,
        *,
        mode="backward",
        policy=None,
        budget=None,
        max_versions=128,
        max_records=1000,
        max_retained_bytes=67_108_864,
    ):
        self._validate_mode(mode)
        for value in (max_versions, max_records, max_retained_bytes):
            if type(value) is not int or value < 1:
                raise InvalidIR("Library retention limits must be positive integers")
        budget = budget if budget is not None else Budget()
        checked = admit(
            model_document if model_document is not None else {"profile": "finite-v0", "declarations": {}},
            budget=budget,
        )
        if checked.model is None:
            error = ResourceLimit if checked.status == "inconclusive" else Rejected
            raise error("Initial model was not admitted", report=checked.report)
        owner = validate_policy(EMPTY_POLICY if policy is None else policy, budget=budget)
        verify_policy(owner, checked.model, budget=budget)
        self._lock = RLock()
        self._instance_id = str(uuid4())
        self._model = checked.model
        self._models = {self._model.version: self._model}
        self._mode, self._policy, self._epoch = mode, encode(owner), 0
        self._max_versions, self._max_records, self._max_bytes = max_versions, max_records, max_retained_bytes
        self._receipts, self._results = {}, {}
        self._sequence = 0
        self._lineage, self._initial_state = [], None
        self._blobs = dict(self._model.artifacts())
        report_key = self._put(
            self._blobs,
            {
                "artifact_kind": "admission",
                "theory_version": self._model.version,
                "report": self._model.report,
            },
        )
        self._support = {
            s: self._put(
                self._blobs,
                {
                    "artifact_kind": "origin",
                    "kind": "authored",
                    "declaration": key,
                    "source_instance_id": self._instance_id,
                    "admission": report_key,
                    "evidence": [],
                },
            )
            for s, key in self._model.index.items()
        }
        self._check_retention(self._blobs)

    @staticmethod
    def _put(blobs, value):
        data = encode(value)
        key = digest(data)
        blobs[key] = data
        return key

    @staticmethod
    def _validate_mode(mode):
        if mode not in ("forward", "backward"):
            raise InvalidIR("Mode must be forward or backward")

    @property
    def instance_id(self):
        return self._instance_id

    @property
    def model(self):
        with self._lock:
            return self._model

    def _context(self):
        return {
            "instance_id": self._instance_id,
            "theory_version": self._model.version,
            "policy_epoch": self._epoch,
            "support_root": digest(encode(self._support)),
        }

    def context(self):
        with self._lock:
            return self._context()

    def info(self):
        with self._lock:
            return {
                **self._context(),
                "mode": self._mode,
                "conformance_root": digest(self._policy),
                "versions": len(self._models),
                "receipt_sequence": self._sequence,
                "persistence": "in_memory",
                "background_learning": False,
            }

    def _expect(self, expected):
        if expected != self._context():
            raise Conflict("Theory, support or owner policy changed; obtain a fresh context")

    def _check_retention(self, blobs, *, extra=0):
        used = sum(map(len, blobs.values())) + len(self._policy)
        used += sum(len(row["envelope_bytes"]) for row in self._receipts.values())
        used += sum(
            len(encode(row["decision"])) for row in self._receipts.values() if row["decision"] is not None
        )
        used += sum(len(value) for value in self._results.values())
        if used + extra > self._max_bytes:
            raise ResourceLimit("Library retention limit reached; export or create another instance")

    def set_mode(self, mode, *, expected_context=None):
        self._validate_mode(mode)
        with self._lock:
            if expected_context is not None:
                self._expect(expected_context)
            if mode != self._mode:
                self._mode, self._epoch = mode, self._epoch + 1
            return self.info()

    def conformance(self):
        with self._lock:
            return {"digest": digest(self._policy), "policy": thaw(read_json(self._policy))}

    def set_conformance(self, source, *, expected_context=None, budget=None):
        budget = budget if budget is not None else Budget()
        with self._lock:
            context, model = self._context(), self._model
            if expected_context is not None:
                self._expect(expected_context)
        policy = validate_policy(source, budget=budget)
        data = encode(policy)
        report = verify_policy(policy, model, budget=budget)
        budget.tick()
        with self._lock:
            self._expect(context)
            self._check_retention(self._blobs, extra=max(0, len(data) - len(self._policy)))
            if data != self._policy:
                self._policy, self._epoch = data, self._epoch + 1
            return {"policy": policy, "digest": digest(data), "report": report}

    def _record(self, row):
        # Receipt envelopes and diagnostics have already been checked separately.
        # Copy the view without applying the input-document limit to their union.
        return thaw(
            {key: value for key, value in row.items() if key not in ("envelope_bytes", "blobs", "token")}
        )

    def candidate(self, candidate_id):
        with self._lock:
            if candidate_id not in self._receipts:
                raise NotFound("Unknown candidate", candidate_id=candidate_id)
            return self._record(self._receipts[candidate_id])

    def receive(self, package, *, review_required=True):
        if type(review_required) is not bool:
            raise InvalidIR("Review requirement must be Boolean")
        envelope, blobs, _, package_hash = unpack(package)
        with self._lock:
            candidate_id = envelope["candidate_id"]
            if candidate_id in self._receipts:
                existing = self._receipts[candidate_id]
                if existing["package_hash"] != package_hash or existing["review_required"] != review_required:
                    raise Conflict("Candidate identity already has different content or review policy")
                return self._record(existing)
            if len(self._receipts) >= self._max_records:
                raise ResourceLimit("Candidate history limit reached")
            combined = {**self._blobs, **blobs}
            self._check_retention(combined, extra=len(package.envelope))
            row = {
                "candidate_id": candidate_id,
                "receipt_sequence": self._sequence + 1,
                "package_hash": package_hash,
                "envelope_bytes": bytes(package.envelope),
                "envelope": envelope,
                "blobs": blobs,
                "review_required": review_required,
                "approval_context": None,
                "status": "awaiting_review" if review_required else "received",
                "attempts": 0,
                "decision": None,
                "token": None,
            }
            result = self._record(row)  # serialization must succeed before a receipt is published
            self._sequence += 1
            self._blobs = combined
            self._receipts[candidate_id] = row
            return result

    def review(self, candidate_id, *, approve, expected_context):
        if type(approve) is not bool:
            raise InvalidIR("Approval must be Boolean")
        with self._lock:
            self._expect(expected_context)
            row = self._receipts.get(candidate_id)
            if row is None:
                raise NotFound("Unknown candidate")
            if row["status"] in TERMINAL:
                raise Conflict("A completed decision cannot be reconsidered")
            if row["status"] == "validating":
                raise Conflict("A candidate is being validated")
            if not approve:
                decision = {"reason": "owner_declined", "context": self._context()}
                self._check_retention(self._blobs, extra=len(encode(decision)))
                row.update(
                    status="rejected",
                    approval_context=None,
                    decision=decision,
                )
            else:
                row.update(status="received", approval_context=_copy(expected_context))
            return self._record(row)

    def decide_next(self, *, budget=None):
        budget = budget if budget is not None else Budget()
        with self._lock:
            row = next((r for r in self._receipts.values() if r["status"] not in TERMINAL), None)
            if row is None or row["status"] == "validating":
                return None
            context, current, policy, mode = self._context(), self._model, self._policy, self._mode
            if row["review_required"] and row["approval_context"] != context:
                row.update(status="awaiting_review", approval_context=None)
                return self._record(row)
            token = str(uuid4())
            row.update(status="validating", token=token, attempts=row["attempts"] + 1)
            base = self._models.get(row["envelope"]["base_theory"])
        try:
            if base is None:
                raise Rejected("Unknown construction base")
            status, model, report, _ = reconcile(row["envelope"], row["blobs"], base, current, mode, budget)
            if status == "accepted":
                report["conformance"] = verify_policy(policy, model, previous=current, budget=budget)
            budget.tick()
        except ResourceLimit as error:
            status, model, report = "inconclusive", None, {"error": error.as_dict(), "work": budget.used}
        except ADMError as error:
            status, model, report = "rejected", None, {"error": error.as_dict(), "work": budget.used}
        except BaseException:
            # Caller interruption or unexpected checker failure never strands a validating head.
            with self._lock:
                row.update(status="received", token=None)
            raise
        with self._lock:
            if self._context() != context:
                row.update(
                    status="awaiting_review" if row["review_required"] else "received",
                    approval_context=None,
                    token=None,
                )
                return self._record(row)
            decision = {
                "mode": mode,
                "policy_epoch": context["policy_epoch"],
                "conformance_root": digest(policy),
                "previous_theory": current.version,
                "theory_version": model.version if status == "accepted" else current.version,
                "report": report,
            }
            try:
                if status == "accepted":
                    blobs, support = self._publication(model, row, decision)
                    if model.version not in self._models and len(self._models) >= self._max_versions:
                        raise ResourceLimit("Theory version limit reached")
                    self._check_retention(blobs, extra=len(encode(decision)))
                result = self._record({**row, "status": status, "decision": decision})
                budget.tick()  # publication preparation consumes the same validation budget
            except ResourceLimit as error:
                status, model = "inconclusive", None
                decision.update(theory_version=current.version, report={"error": error.as_dict()})
                result = self._record({**row, "status": status, "decision": decision})
            except BaseException:
                row.update(status="received", token=None)
                raise
            if status != "accepted":
                try:
                    self._check_retention(self._blobs, extra=len(encode(decision)))
                except BaseException:
                    # Even a rejection needs room for its audit record. Leave the
                    # head retryable rather than silently exceeding its allowance.
                    row.update(status="received", token=None)
                    raise
            if status == "accepted":
                self._model, self._blobs, self._support = model, blobs, support
                self._models[model.version] = model
            row.update(status=status, decision=decision, token=None)
            return result

    def _publication(self, model, row, decision):
        blobs = {**self._blobs, **model.artifacts()}
        report = self._put(
            blobs, {"artifact_kind": "admission", "theory_version": model.version, "report": model.report}
        )
        proposed = {p["symbol"]: p["artifact"] for p in row["envelope"]["proposals"]}
        support = {}
        for symbol, declaration in model.index.items():
            if symbol in proposed:
                wrapper = read_json(row["blobs"][proposed[symbol]])
                support[symbol] = self._put(
                    blobs,
                    {
                        "artifact_kind": "origin",
                        "kind": "learning",
                        "declaration": declaration,
                        "source_instance_id": self._instance_id,
                        "admission": report,
                        "evidence": thaw(wrapper["evidence"]),
                        "candidate_id": row["candidate_id"],
                        "receipt_sequence": row["receipt_sequence"],
                        "mode": decision["mode"],
                        "policy_epoch": decision["policy_epoch"],
                    },
                )
            else:
                if self._model.index.get(symbol) != declaration:
                    raise Rejected("Unproposed changed declaration has no matching evidence support")
                support[symbol] = self._support[symbol]
        return blobs, support

    def query(self, query, *, limits=None, lean=None):
        limits = {**DEFAULT_LIMITS, **(limits or {})}
        query = normalize_query(query, limits)
        budget = Budget(limits["max_work"], limits["max_duration_ms"] / 1000)
        with self._lock:
            model, context = self._model, self._context()
            if len(self._results) >= self._max_records:
                raise ResourceLimit("Result history limit reached")
        result = execute(model, query, limits, budget=budget, lean=lean, explain=self.explain)
        binding = result.get("binding", {})
        body = {key: value for key, value in binding.items() if key != "digest"}
        if (
            binding.get("profile") != "adm-result/0.1"
            or binding.get("theory_version") != model.version
            or encode(binding.get("query")) != encode(semantic_query(query))
            or binding.get("digest") != digest(encode(body))
        ):
            raise StorageError("Local result binding differs from the pinned query")
        request_id, attempt_id, result_id = str(uuid4()), str(uuid4()), str(uuid4())
        result.update(
            result_id=result_id,
            execution={
                **context,
                "request_id": request_id,
                "attempt_id": attempt_id,
                "query_digest": digest(encode(semantic_query(query))),
            },
        )
        data = encode(result)
        result = _copy(result)
        with self._lock:
            if len(self._results) >= self._max_records:
                raise ResourceLimit("Result history limit reached")
            self._check_retention(self._blobs, extra=len(data))
            self._results[result_id] = data
        return result

    def explain(self, result_id):
        with self._lock:
            if result_id not in self._results:
                raise NotFound("Unknown local result")
            return thaw(read_json(self._results[result_id]))

    def export_snapshot(self, *, state=None, budget=None):
        from .snapshots import export_instance

        with self._lock:
            pinned = {
                "instance_id": self._instance_id,
                "model": self._model,
                "support": dict(self._support),
                "blobs": dict(self._blobs),
                "lineage": _copy(self._lineage),
                "policy": self._policy,
            }
        return export_instance(pinned, state=state, budget=budget)

    @classmethod
    def restore(cls, package, *, mode="backward", budget=None, **limits):
        from .snapshots import MAX_LINEAGE, validate_snapshot

        budget = budget if budget is not None else Budget()
        checked = validate_snapshot(package, budget=budget)
        if len(checked["lineage"]) >= MAX_LINEAGE:
            raise ResourceLimit("Snapshot restore would exceed lineage limit")
        result = cls(
            checked["model"].document(), mode=mode, policy=checked["conformance"], budget=budget, **limits
        )
        result._blobs.update(checked["blobs"])
        result._support = dict(checked["support"])
        result._lineage = [
            *checked["lineage"],
            {
                "package_id": package.package_id,
                "source_instance_id": checked["manifest"]["source_instance_id"],
                "source_theory_version": checked["model"].version,
            },
        ]
        result._initial_state = _copy(checked["state"])
        result._check_retention(result._blobs)
        return result

    def lineage(self):
        with self._lock:
            return _copy(self._lineage)

    def initial_state(self):
        with self._lock:
            return _copy(self._initial_state)
