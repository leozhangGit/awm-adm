"""Check untrusted preparation in the bounded network-free compute process.

Headers are checked without fabricating executable bodies or a serving Model.
Requirements remain proposals, never evidence of independent domain correctness.
"""

from pydantic import ValidationError

from ..engine import types as ty
from ..engine import validate_snapshot
from ..engine.acquisition import validate_contract
from ..engine.artifacts import digest
from ..engine.conformance import validate_policy
from ..engine.construction import interfaces
from ..engine.data import encode, name, thaw
from ..engine.errors import ADMError, ResourceLimit, TypeMismatch
from ..engine.model import declaration_references
from ..language.parser import catalog, validate_vocabulary
from ..runtime.protocol import unpack
from ..wire import check_tree, decode
from .diagnostics import PreparationError, diagnostic
from .models import Plan, Reply
from .provider_format import PROFILE, WireReply, local_plan


class Headers:
    """Vocabulary validation view; explicitly not an executable model."""

    def __init__(self, accepted, proposed, budget):
        self.declarations = {**accepted.document()["declarations"], **proposed}
        self.types = {}
        self.proposed, self.budget, self.visiting = proposed, budget, set()
        for symbol, header in proposed.items():
            if header["kind"] == "type":
                self.resolve(symbol)
        for header in proposed.values():
            for field in ("params",):
                if field in header:
                    if not isinstance(header[field], dict) or len(header[field]) > 32:
                        raise ValueError("Use at most 32 named parameters")
                    for param, spec in header[field].items():
                        name(param)
                        self.parse(spec)
            for field in ("returns", "state", "parameters"):
                if field in header:
                    self.parse(header[field])

    def resolve(self, symbol):
        self.budget.tick()
        if symbol not in self.types and symbol in self.declarations:
            if symbol in self.visiting:
                raise ValueError("Cyclic proposed type")
            header = self.declarations[symbol]
            if header["kind"] != "type":
                raise ValueError("Type reference must name a type")
            self.visiting.add(symbol)
            t = self.parse(header["type"])
            self.visiting.remove(symbol)
            self.types[symbol] = t
            return t
        if symbol not in self.types:
            raise ValueError("Unknown type reference")
        t = self.types[symbol]
        self.size(t)
        return t

    def parse(self, spec):
        t = ty.parse(spec, self.resolve)
        self.size(t)
        return t

    def size(self, t):
        self.budget.tick()
        if t.kind == "bool":
            n = 2
        elif t.kind == "int":
            n = t.parts[1] - t.parts[0] + 1
        elif t.kind == "enum":
            n = len(t.parts)
        elif t.kind == "vector":
            n = self.size(t.parts[0]) ** t.parts[1]
        elif t.kind in {"record", "sum"}:
            n = 1 if t.kind == "record" else 0
            for _, part in t.parts:
                count = self.size(part)
                n = n * count if t.kind == "record" else n + count
                if n > 65536:
                    break
        else:
            raise ValueError(
                "Preparation supports plain finite carriers; refinement and presentation synthesis need explicit local design"
            )
        if not 1 <= n <= 65536:
            raise ValueError("Narrow each proposed carrier to between 1 and 65536 values")
        return n

    def document(self):
        return {"declarations": self.declarations}

    def capabilities(self, *, budget):
        budget.tick()
        return {"modules": sorted({s.rsplit(".", 1)[0] for s in self.declarations})}

    def validate_value(self, spec, value, *, budget):
        if not ty.contains(self.parse(spec), value, budget, None):
            raise TypeMismatch("Value alias is outside its parameter carrier")


def compute(task, budget):
    checked = validate_snapshot(unpack(task["snapshot"]), budget=budget)
    model = checked["model"]
    if (
        model.version != task["context"]["theory_version"]
        or digest(encode(checked["support"])) != task["context"]["support_root"]
    ):
        raise ValueError("Teaching context does not match accepted snapshot")
    vocabulary = validate_vocabulary(model, task["vocabulary"], budget)
    base = {"catalog": catalog(model, vocabulary, budget), "requirements": thaw(checked["conformance"])}
    if task["operation"] == "teaching_catalog":
        return {**base, "work": budget.used}
    stage = {"name": "wire"}
    try:
        return check_reply(task, budget, model, vocabulary, base, stage)
    except ResourceLimit:
        raise  # Exhaustion remains inconclusive, never a provider-format error.
    except PreparationError as error:
        return {"failure": error.diagnostic, "work": budget.used}
    except (ValueError, TypeError, KeyError, ADMError) as error:
        code = "invalid_fields" if isinstance(error, ValidationError) else "invalid_value"
        if isinstance(error, ValidationError) and stage["name"] == "envelope":
            first = error.errors(include_url=False, include_input=False, include_context=False)[0]["loc"]
            if first and first[0] == "plan":
                stage["name"] = "plan"
                for field, section in (
                    ("types", "types"),
                    ("interfaces", "interfaces"),
                    ("material", "sources"),
                    ("aliases", "vocabulary"),
                    ("parameters", "vocabulary"),
                    ("value_aliases", "vocabulary"),
                ):
                    if field in first:
                        stage["name"] = section
                        break
        if isinstance(error, ADMError):
            code = error.code
        return {"failure": diagnostic(stage["name"], code, error), "work": budget.used}


def check_reply(task, budget, model, vocabulary, base, stage):
    text = task["provider_text"]
    if len(text.encode()) > 98304:
        raise PreparationError("wire", "reply_too_large")
    value = decode(text.encode())
    stage["name"] = "envelope"
    if task.get("reply_format") == PROFILE:
        value = WireReply.model_validate(value).model_dump()
        if (value["status"] == "ready") != (value["plan"] is not None):
            raise PreparationError("envelope", "status_plan_mismatch")
        reply = {"status": value["status"], "message": value["message"], "plan_json": None}
        if reply["status"] != "ready":
            return {"reply": reply, "work": budget.used}
        stage["name"] = "plan"
        value = local_plan(value["plan"], budget)
    elif task.get("reply_format") is None:
        # Only recorded/in-flight legacy contracts use the historical envelope.
        reply = Reply.model_validate(value).model_dump()
        if reply["status"] != "ready":
            return {"reply": reply, "work": budget.used}
        stage["name"] = "plan_json"
        value = decode(reply["plan_json"].encode())
    else:
        raise PreparationError("envelope", "unsupported_format")
    stage["name"] = "plan"
    check_tree(value)
    plan = Plan.model_validate(value).model_dump()
    allowed = set(task["input_ids"])
    proposed, contracts, used = {}, [], set()
    accepted = model.document()["declarations"]
    for child in plan["children"]:
        budget.tick()
        stage["name"] = "inputs"
        ids = set(child["input_ids"])
        if not ids <= allowed or len(ids) != len(child["input_ids"]):
            raise ValueError("Child evidence must reference exact supplied owner turns")
        used |= ids
        stage["name"] = "interfaces"
        contract = validate_contract(
            {
                "profile": "adm-acquisition/1",
                "required_symbols": list(child["interfaces"]),
                "allowed_helpers": [],
                "interfaces": child["interfaces"],
                "allowed_retractions": [],
                "max_declarations": 32,
                "max_bytes": 65536,
            }
        )
        headers = interfaces(contract)
        for symbol, header in headers.items():
            if header["kind"] == "presentation":
                raise ValueError("Algebraic presentation synthesis requires explicit local design")
            if symbol in proposed:
                raise ValueError("Children must not propose competing interfaces")
            if symbol in accepted and child["kind"] != "correction":
                raise ValueError("Existing symbols need an explicit correction objective")
            proposed[symbol] = header
        contracts.append(contract if headers else None)
    stage["name"] = "inputs"
    if used != allowed:
        raise ValueError("Every supplied intention/material turn must remain linked to a child")
    stage["name"] = "dependencies"
    owners = {symbol: i for i, child in enumerate(plan["children"]) for symbol in child["interfaces"]}
    dependencies = []
    for i, child in enumerate(plan["children"]):
        dependencies.append(
            sorted(
                {
                    owners[ref]
                    for h in child["interfaces"].values()
                    for ref in declaration_references(h)
                    if ref in owners and owners[ref] != i
                }
            )
        )

    def visit(i, path):
        budget.tick()
        if i in path:
            raise ValueError("Child interface dependencies are cyclic")
        for parent in dependencies[i]:
            visit(parent, path | {i})

    for i in range(len(dependencies)):
        visit(i, set())
    stage["name"] = "types"
    view = Headers(model, proposed, budget)
    stage["name"] = "vocabulary"
    merged = {k: {**vocabulary[k], **plan["vocabulary"][k]} for k in vocabulary}
    plan["vocabulary"] = validate_vocabulary(view, merged, budget)
    stage["name"] = "requirements"
    if plan["requirements"] is not None:
        additions = validate_policy(plan["requirements"], budget=budget)
        old_ids = {c["contract_id"] for c in base["requirements"]["contracts"]}
        if any(c["contract_id"] in old_ids for c in additions["contracts"]):
            raise ValueError("Proposed requirements cannot replace existing owner contracts")
        for c in additions["contracts"]:
            if not set(c["required_symbols"]) <= set(view.declarations):
                raise ValueError("Proposed requirement references an unknown interface")
        plan["requirements"] = thaw(additions)
    return {
        "reply": {**reply, "plan_json": None},
        "plan": plan,
        "contracts": contracts,
        "dependencies": dependencies,
        "owner_requirements_digest": digest(encode(base["requirements"])),
        "work": budget.used,
    }
