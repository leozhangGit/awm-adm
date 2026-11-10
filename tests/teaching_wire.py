"""Author recorded provider replies in the native format; never used by runtime."""

from copy import deepcopy

from awm_adm.runtime.protocol import dumps, loads
from awm_adm.teaching.provider_format import PROFILE


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
