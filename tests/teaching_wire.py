"""Author recorded provider replies in the native format; never used by runtime."""

from copy import deepcopy

from awm_adm.runtime.protocol import dumps, loads
from awm_adm.teaching.provider_format import MATERIAL_PROFILE, PROFILE, SHARED_PROFILE


def selected_reply(reply, manifest):
    """Author current synthetic selections for existing fixture helpers.

    Explicit current-wire tests pass their own IDs unchanged. This conversion is
    test-only: production never accepts invented provider source identities.
    """
    reply = deepcopy(native_reply(reply))
    if reply.get("profile") != PROFILE:
        return reply
    reply["profile"] = MATERIAL_PROFILE
    for child in (reply.get("plan") or {}).get("children", []):
        if not child.get("material"):
            continue
        material = child["material"]
        source_ids = {s["source_id"] for s in material.pop("sources")}
        available = [e for e in manifest["entries"] if set(e["input_ids"]) & set(child["input_ids"])]
        selected = [e for e in available if e["kind"] == "upload" and e["source_id"] in source_ids]
        if not selected:
            selected = [e for e in available if e["kind"] == "queue"] or [
                e for e in available if e["kind"] == "message"
            ]
        material["material_ids"] = [e["id"] for e in selected]
    return reply


def shared_reply(reply, manifest):
    """Author new-wire fixtures only; never merge different intended projections."""
    reply = selected_reply(reply, manifest)
    if reply.get("profile") != MATERIAL_PROFILE:
        return reply
    reply["profile"] = SHARED_PROFILE
    if reply["plan"] is not None:
        projections = [c["material"].pop("projection") for c in reply["plan"]["children"] if c["material"]]
        assert not projections or all(p == projections[0] for p in projections)
        reply["plan"]["source_projection"] = projections[0] if projections else None
    return reply


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


def temporal_reply(reply, manifest):
    from awm_adm.teaching.provider_format import TEMPORAL_PROFILE

    reply = shared_reply(reply, manifest)
    if reply.get("profile") != SHARED_PROFILE:
        return reply
    reply["profile"] = TEMPORAL_PROFILE
    if reply["plan"] is not None:
        old = reply["plan"].pop("source_projection")
        catalog = deepcopy(old) if old else None
        if catalog:
            catalog["profile"] = "awm-adm-temporal-catalog/1"
            catalog["predicates"] = [
                {
                    **p,
                    "meaning": p["symbol"],
                    "statement_level": "direct",
                    "actor": None,
                    "modality": None,
                    "qualifiers": [],
                    "scope_kinds": ["instant", "validity"],
                    "metric": None,
                }
                for p in catalog["predicates"]
            ]
            for c in catalog["cells"]:
                c["kind"] = {"point": "instant", "interval": "validity"}.get(c["kind"], c["kind"])
                c.pop("granularity", None)
        if catalog:
            for cell in catalog["cells"]:
                cell.update(precision="second", timezone_basis="UTC")
        reply["plan"]["evidence_scope"] = catalog
    return reply


def assessed_reply(reply, input_ids, *, temporal=True):
    """Upgrade authored fixtures only; production never guesses a gap from prose."""
    reply = deepcopy(reply)
    if reply.get("profile") in {"awm-adm-teaching-reply/6", "awm-adm-teaching-reply/7"}:
        return reply
    status = reply.pop("status")
    reply["profile"] = "awm-adm-teaching-reply/6" if temporal else "awm-adm-teaching-reply/7"
    reply.update(missing_information=[], unsupported_capabilities=[], question=None)
    if status == "needs_clarification":
        reply["question"] = reply["message"]
        reply["missing_information"] = [
            {
                "kind": "meaning",
                "input_ids": input_ids,
                "subject": "Requested meaning",
                "detail": reply["message"],
            }
        ]
    elif status == "unsupported":
        reply["unsupported_capabilities"] = [
            {
                "kind": "unsupported_representation",
                "input_ids": input_ids,
                "requested_capability": "Authored unsupported fixture",
                "limitation": reply["message"],
            }
        ]
    return reply
