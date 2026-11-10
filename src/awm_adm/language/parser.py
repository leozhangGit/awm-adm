"""Controlled language over a checked model. Domain vocabulary is instance data."""

import json
import re

from ..engine import types as ty
from ..engine.artifacts import digest
from ..engine.data import encode, read_json
from ..engine.errors import ADMError, KnowledgeGap, ResourceLimit
from ..wire import decode
from .models import Vocabulary

PROFILE = "awm-adm-local-language/0.1"
FLAGS = re.IGNORECASE | re.ASCII
SAFE_INTEGER = 9_007_199_254_740_991


class Clarify(Exception):
    def __init__(self, message, *, status="needs_clarification", choices=()):
        self.message, self.status, self.choices = message, status, list(choices)


def blocked(text):
    return bool(
        re.match(
            r"^(?:switch|change|set|delete|archive|rotate|enable|disable|learn|teach|forget)\b",
            text.strip(),
            FLAGS,
        )
    )


def safe_values(value):
    if type(value) is float or (type(value) is int and abs(value) > SAFE_INTEGER):
        raise Clarify("Supply an exact finite integer; decimals and implicit conversions are unsupported.")
    if isinstance(value, dict):
        for item in value.values():
            safe_values(item)
    if isinstance(value, list):
        for item in value:
            safe_values(item)


def json_prefix(text):
    """Locate one JSON value, then strictly decode it; do not split inside strings."""
    text = text.lstrip()
    try:
        _, end = json.JSONDecoder().raw_decode(text)
        value = decode(text[:end].encode())
    except (ValueError, RecursionError):
        raise Clarify("Supply valid JSON with unique keys.", status="unsupported") from None
    safe_values(value)
    return value, text[end:].strip()


def catalog(model, metadata, budget):
    vocabulary = Vocabulary.model_validate(metadata).model_dump()
    declarations = model.document()["declarations"]
    # Bodies, evidence and provider credentials are never language-catalog fields.
    entries = {
        symbol: {
            k: value
            for k, value in d.items()
            if k in {"kind", "type", "params", "returns", "state", "parameters"}
        }
        for symbol, d in declarations.items()
        if d["kind"] in {"type", "function", "transition", "goal"}
    }
    budget.tick(len(entries) + 1)
    body = {
        "profile": PROFILE,
        "declarations": entries,
        "modules": model.capabilities(budget=budget)["modules"],
        "vocabulary": vocabulary,
    }
    if len(encode(body)) > 262144:
        raise ResourceLimit("Language catalog exceeds 256 KiB")
    return {**body, "digest": digest(encode(body))}


def validate_vocabulary(model, metadata, budget):
    value = Vocabulary.model_validate(metadata).model_dump()
    declarations = model.document()["declarations"]
    modules = model.capabilities(budget=budget)["modules"]
    for alias, targets in value["aliases"].items():
        budget.tick()
        if not targets or len(targets) > 16 or len(set(targets)) != len(targets):
            raise ValueError("Alias must name one to sixteen distinct catalog entries")
        if any(t not in declarations and t not in modules for t in targets):
            raise ValueError("Alias target is not accepted model vocabulary")
        if alias in declarations or alias in modules:
            raise ValueError("Aliases cannot override exact qualified symbols or module names")
    for field in ("parameter_units", "parameter_roles", "value_aliases"):
        for symbol, settings in value[field].items():
            budget.tick()
            d = declarations.get(symbol, {})
            if d.get("kind") != "function" or not set(settings) <= set(d["params"]) or len(settings) > 64:
                raise ValueError("Parameter metadata requires accepted function parameters")
            for name, setting in settings.items():
                if field == "parameter_units" and (not setting or len(setting) > 100):
                    raise ValueError("Units must be explicit bounded labels")
                if field == "value_aliases":
                    if len(setting) > 64:
                        raise ValueError("Too many entity/value aliases")
                    for alias, item in setting.items():
                        if not alias or len(alias) > 100:
                            raise ValueError("Invalid value alias")
                        safe_values(item)
                        model.validate_value(d["params"][name], item, budget=budget)
                        # An already-valid literal must not be reassigned a different meaning.
                        try:
                            model.validate_value(d["params"][name], alias, budget=budget)
                        except ResourceLimit:
                            raise
                        except ADMError:
                            continue
                        if item != alias:
                            raise ValueError("Value aliases cannot override accepted literals")
    return value


def resolve(name, cat, kinds, *, module=None):
    declarations = cat["declarations"]
    available = (
        set(cat["modules"])
        if kinds == {"module"}
        else {
            k
            for k, d in declarations.items()
            if d["kind"] in kinds and (module is None or k.rsplit(".", 1)[0] == module)
        }
    )
    if name in available:
        return name
    if "." in name:
        if name in declarations:
            raise Clarify("The named declaration has a different kind or module.")
        raise Clarify(
            "The specified declaration is missing. Learning requires a separate task and budget.",
            status="needs_learning",
        )
    targets = set(cat["vocabulary"]["aliases"].get(name, [])) | {
        s for s in available if s.rsplit(".", 1)[-1] == name
    }
    found = sorted(targets & available)
    if len(found) == 1:
        return found[0]
    if not found:
        raise Clarify(
            "Choose a known qualified symbol or supply the missing entity, time and supported request form.",
            choices=sorted(available)[:16],
        )
    raise Clarify("This name has several meanings; use a qualified symbol.", choices=found[:16])


def arguments(model, cat, symbol, raw, budget):
    params = cat["declarations"][symbol]["params"]
    if not isinstance(raw, dict) or set(raw) != set(params):
        raise Clarify("Supply exactly these parameters: " + (", ".join(params) or "none (use {})"))
    result = {}
    for name, spec in params.items():
        value = raw[name]
        unit = cat["vocabulary"]["parameter_units"].get(symbol, {}).get(name)
        if unit:
            if not isinstance(value, dict) or set(value) != {"value", "unit"} or value["unit"] != unit:
                raise Clarify(
                    f"Parameter {name} requires an explicit value/unit object with unit {unit}; no conversion is inferred."
                )
            value = value["value"]
        aliases = cat["vocabulary"]["value_aliases"].get(symbol, {}).get(name, {})
        if isinstance(value, str) and value in aliases:
            value = aliases[value]
        model.validate_value(spec, value, budget=budget)
        result[name] = {"op": "literal", "value": value, "type": spec}
    return result


def check_query(model, query, budget, results=()):
    """Validate intent without evaluating functions or searching for a plan."""
    op = query["op"]
    if op in ("evaluate", "check_claim"):
        expression = query["expression" if op == "evaluate" else "proposition"]
        if query["module"] not in model.capabilities(budget=budget)["modules"]:
            raise KnowledgeGap("Unknown query module")
        model.expression_dependencies(expression)
        # Explicit adapter to the owned finite type checker; no answer is computed.
        inferred = model._interpreter.infer(read_json(expression), {}, budget)
        if op == "check_claim":
            model._interpreter.expect(inferred, ty.BOOL)
    elif op == "find_plan":
        scope = model.planning_scope(query["module"], query["goal"], query.get("transitions"), budget=budget)
        model.validate_value(scope["state_type"], query["initial_state"], budget=budget)
    elif op == "explain":
        if query["result_id"] not in results:
            raise Clarify("Choose a recorded successful result from this ADM.")
    elif op != "capabilities":
        raise Clarify(
            "This operation uses the structured interface or explicit owner controls.", status="unsupported"
        )
    return query


def parse(model, cat, utterance, budget, *, results=()):
    try:
        text = utterance.strip()
        if not text or len(text) > 16384:
            raise Clarify("Supply a request within the 16,384-character limit.", status="unsupported")
        if blocked(text):
            raise Clarify(
                "Use Teach for a learning proposal or explicit Settings/Connections for administration.",
                status="unsupported",
            )
        if re.fullmatch(r"(?:capabilities|list capabilities|what can you do\?)", text, FLAGS):
            query = {"op": "capabilities"}
        elif match := re.fullmatch(r"(?:evaluate|what is|is) (.+)", text, FLAGS):
            tail = match[1]
            natural = not text.lower().startswith("evaluate ")
            if natural and tail.endswith("?"):
                tail = tail[:-1].strip()
            pieces = re.split(r"\s+with\s+", tail, maxsplit=1, flags=FLAGS)
            symbol = resolve(pieces[0].strip(), cat, {"function"})
            params = cat["declarations"][symbol]["params"]
            if len(pieces) == 1:
                if params or not natural:
                    raise Clarify("Supply 'with' and a JSON object containing all function arguments.")
                values = {}
            else:
                values, rest = json_prefix(pieces[1])
                if rest:
                    raise Clarify("Unexpected text after the argument object.", status="unsupported")
            call = {"op": "call", "function": symbol, "args": arguments(model, cat, symbol, values, budget)}
            claim = text.lower().startswith("is ")
            query = {
                "op": "check_claim" if claim else "evaluate",
                "module": symbol.rsplit(".", 1)[0],
                "proposition" if claim else "expression": call,
            }
        elif match := re.fullmatch(r"check (\S+) claim(?:\s+(.*))?", text, FLAGS):
            module = resolve(match[1], cat, {"module"})
            if not match[2]:
                raise Clarify("Supply a Boolean JSON expression.")
            expression, rest = json_prefix(match[2])
            if rest:
                raise Clarify("Unexpected text after the claim.", status="unsupported")
            query = {"op": "check_claim", "module": module, "proposition": expression}
        elif text.lower().startswith("plan "):
            match = re.fullmatch(r"plan (\S+) to (\S+)(?: from (.*))?", text, FLAGS)
            if not match:
                raise Clarify(
                    "Supply: plan MODULE to GOAL from JSON_STATE, with optional using and within clauses."
                )
            module = resolve(match[1], cat, {"module"})
            goal = resolve(match[2], cat, {"goal"}, module=module)
            if not match[3]:
                raise Clarify("An explicit initial state is required.")
            state, rest = json_prefix(match[3])
            actions, depth = None, None
            if re.match(r"^using\s+", rest, FLAGS):
                selection, rest = json_prefix(re.sub(r"^using\s+", "", rest, count=1, flags=FLAGS))
                if not isinstance(selection, list) or any(not isinstance(s, str) for s in selection):
                    raise Clarify("Supply a JSON list of action names.")
                actions = [resolve(s, cat, {"transition"}, module=module) for s in selection]
                if len(set(actions)) != len(actions):
                    raise Clarify("Selected actions must be distinct.")
            if rest:
                match_depth = re.fullmatch(r"within ([0-9]{1,7}) steps", rest, FLAGS)
                if not match_depth or int(match_depth[1]) > 1_000_000:
                    raise Clarify(
                        "Use 'within INTEGER steps' with a depth of 0–1,000,000.", status="unsupported"
                    )
                depth = int(match_depth[1])
            query = {
                "op": "find_plan",
                "module": module,
                "goal": goal,
                "initial_state": state,
                "transitions": actions,
                "max_depth": depth,
            }
        elif match := re.fullmatch(r"explain (\S+)", text, FLAGS):
            query = {"op": "explain", "result_id": match[1]}
        else:
            raise Clarify(
                "This phrasing is outside the local language subset. Use a catalog example, clarify, or explicitly select external interpretation.",
                status="unsupported",
            )
        check_query(model, query, budget, results)
        return {"status": "ready", "query": query, "assumptions": [], "clarification": None, "choices": []}
    except ResourceLimit:
        raise
    except Clarify as error:
        return {
            "status": error.status,
            "query": None,
            "assumptions": [],
            "clarification": error.message,
            "choices": error.choices,
        }
    except KnowledgeGap:
        return {
            "status": "needs_learning",
            "query": None,
            "assumptions": [],
            "clarification": "A named declaration is missing. No learning call has been authorized.",
            "choices": [],
        }
    except (ADMError, ValueError, TypeError, KeyError):
        return {
            "status": "needs_clarification",
            "query": None,
            "assumptions": [],
            "clarification": "The supplied values or expression do not match the accepted finite types. Check entity, unit, time, state and Boolean/integer distinctions.",
            "choices": [],
        }
