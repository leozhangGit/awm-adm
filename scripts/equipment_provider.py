"""Synthetic equipment replies for isolated verification only; no network or credentials."""

from copy import deepcopy
from pathlib import Path

from awm_adm.runtime.protocol import dumps, loads
from awm_adm.teaching.provider_format import PROFILE

ROOT = Path(__file__).resolve().parents[1] / "examples/equipment"


def fixture(name):
    return loads((ROOT / name).read_bytes())


def native_reply(reply):
    if "plan_json" not in reply:
        return reply
    reply = deepcopy(reply)
    raw = reply.pop("plan_json")
    if raw is None:
        return {"profile": PROFILE, **reply, "plan": None}
    plan = loads(raw.encode())
    nodes = []

    def node(spec):
        uid = f"t{len(nodes)}"
        value = {
            "id": uid,
            "kind": spec.get("kind", "ref"),
            "minimum": None,
            "maximum": None,
            "values": [],
            "members": [],
            "element_id": None,
            "length": None,
            "symbol": None,
        }
        nodes.append(value)
        if "ref" in spec:
            value["symbol"] = spec["ref"]
        elif spec["kind"] == "int":
            value.update(minimum=spec["min"], maximum=spec["max"])
        elif spec["kind"] == "enum":
            value["values"] = spec["values"]
        elif spec["kind"] in ("record", "sum"):
            key = "fields" if spec["kind"] == "record" else "variants"
            value["members"] = [{"name": k, "type_id": node(v)} for k, v in spec[key].items()]
        elif spec["kind"] == "vector":
            value.update(element_id=node(spec["element"]), length=spec["length"])
        return uid

    children = []
    for c in plan["children"]:
        headers = []
        for symbol, h in c.get("interfaces", {}).items():
            header = {
                "symbol": symbol,
                "kind": h["kind"],
                "type_id": None,
                "params": [],
                "returns_id": None,
                "state_id": None,
                "parameters_id": None,
            }
            for k, v in h.items():
                if k in {"type", "returns", "state", "parameters"}:
                    header[k + "_id"] = node(v)
                elif k == "params":
                    header[k] = [{"name": n, "type_id": node(t)} for n, t in v.items()]
                else:
                    header[k] = v  # Retain injected extra fields for rejection tests.
            headers.append(header)
        material = deepcopy(c.get("material"))
        if material:
            projection = material["projection"]
            projection.setdefault("profile", "awm-adm-projection/1")
            for predicate in projection["predicates"]:
                predicate.setdefault("minimum", 0)
                predicate.setdefault("maximum", 100)
                predicate.setdefault("values", [])
            for cell in projection["cells"]:
                cell.setdefault("effective_from", None)
                cell.setdefault("effective_to", None)
            for source in material["sources"]:
                source.setdefault("allow_external", False)
        children.append({**c, "interfaces": headers, "material": material})
    v = plan.get("vocabulary", {})
    symbols = set(v.get("parameter_units", {})) | set(v.get("parameter_roles", {}))
    params = []
    for symbol in sorted(symbols):
        units, roles = (
            v.get("parameter_units", {}).get(symbol, {}),
            v.get("parameter_roles", {}).get(symbol, {}),
        )
        params.extend(
            {"symbol": symbol, "parameter": p, "unit": units.get(p), "role": roles.get(p)}
            for p in sorted(set(units) | set(roles))
        )
    new = {
        k: val for k, val in plan.items() if k not in {"profile", "children", "vocabulary", "requirements"}
    }
    new.update(
        types=nodes,
        children=children,
        aliases=[{"alias": k, "targets": t} for k, t in v.get("aliases", {}).items()],
        parameters=params,
        value_aliases=[
            {"symbol": s, "parameter": p, "alias": a, "value_json": dumps(val).decode()}
            for s, ps in v.get("value_aliases", {}).items()
            for p, aliases in ps.items()
            for a, val in aliases.items()
        ],
        requirements_json=dumps(plan["requirements"]).decode()
        if plan.get("requirements") is not None
        else None,
    )
    return {"profile": PROFILE, **reply, "plan": new}


def recorded_reply(wire):
    body = loads(wire)
    ctx = loads(body["input"][0]["content"].encode())
    name = body["text"]["format"]["name"]
    if name == "adm_teaching_preparation":
        ids = [i["id"] for i in ctx["inputs"]]
        policy = fixture("source-policy.json")
        policy["sources"][0]["source_id"] = "documents"
        plan = {
            "kind": "mixed",
            "summary": "Borrowing advice and two years of camera-kit history",
            "children": [
                {
                    "kind": "capability",
                    "objective": "Advise on one further checkout",
                    "input_ids": ids,
                    "interfaces": fixture("task.json")["acquisition_contract"]["interfaces"],
                },
                {
                    "kind": "facts",
                    "objective": "Retain 2025 and 2026 camera-kit capacity",
                    "input_ids": ids,
                    "material": policy,
                },
            ],
            "vocabulary": {"aliases": {"borrow": ["equipment.can_borrow"]}},
            "requirements": None,
        }
        return native_reply(
            {
                "status": "ready",
                "message": "Review the borrowing rule and dated capacity scope.",
                "plan_json": dumps(plan).decode(),
            }
        )
    if name == "adm_construction_v1":
        return fixture("recorded-acquisition.json")
    if name == "adm_source_claims_v1":
        content = ctx["source"]["content"]
        claims = []
        for year in (2025, 2026):
            line = next(
                line
                for line in content.splitlines()
                if line.startswith("The camera-kit") and f"from {year}-" in line
            )
            start = len(content[: content.index(line)].encode())
            claims.append(
                {
                    **fixture(f"history-{year}.json"),
                    "start_byte": start,
                    "end_byte": start + len(line.encode()),
                }
            )
        return {"claims": claims}
    if name == "adm_teaching_completion":
        return {
            "packet_digest": ctx["packet_digest"],
            "accepted_ids": ctx["packet"]["accepted_ids"],
            "unresolved_ids": ctx["packet"]["unresolved_ids"],
            "explanation": "The advisory borrowing rule and the two dated capacity facts were accepted. No inventory was changed; 2027 remains unknown.",
            "authority": "explanation_only",
        }
    if name == "adm_ask_intent":
        text = ctx["utterance"]
        cmd = fixture("expected.json")["local_command"]
        if "capacity" in text:
            year = 2027 if "2027" in text else 2026
            cmd = (
                "lookup fact with "
                + dumps(
                    {
                        "entity_id": "camera-kit",
                        "predicate": "equipment.capacity",
                        "effective_at": f"{year}-01-01T00:00:00Z",
                    }
                ).decode()
            )
        return {"status": "ready", "command": cmd, "assumptions": [], "clarification": None}
    if name == "adm_ask_explanation":
        return {
            "packet_digest": ctx["digest"],
            "outcome_digest": ctx["outcome_digest"],
            "status": ctx["outcome"]["status"],
            "claim_ids": ["outcome"],
            "support_ids": ctx["support_ids"],
            "explanation": ctx["allowed_claims"][0]["text"],
            "authority": "explanation_only",
        }
    raise AssertionError(name)
