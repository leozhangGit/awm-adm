"""Close a conversational correction over its accepted dependency graph."""

from ..engine.admission import dependent_closure
from ..engine.construction import SLOTS
from ..engine.errors import InvalidIR


def preserve_dependents(model, plan, budget):
    """Keep unrequested dependent bodies pinned; all are admitted again atomically.

    Explicitly revised declarations remain provider work. Reusing an accepted body
    is not importing proof status or asserting that it still passes validation.
    Overlapping correction groups must be expressed as one atomic child.
    """
    accepted = model.document()["declarations"]
    owners = {s: i for i, c in enumerate(plan["children"]) for s in c["interfaces"]}
    retained = []
    for i, child in enumerate(plan["children"]):
        roots = set(child["interfaces"]) & accepted.keys()
        if roots and child["kind"] != "correction":
            raise InvalidIR("Existing symbols need an explicit correction objective")
        affected = dependent_closure(model, roots, budget) if roots else set()
        extra = sorted(affected - child["interfaces"].keys())
        if any(s in owners and owners[s] != i for s in extra):
            raise InvalidIR("Dependent corrections must be in the same atomic teaching child")
        if len(child["interfaces"]) + len(extra) > 32:
            raise InvalidIR("Correction and dependent declarations exceed the 32-declaration bound")
        pinned = {}
        for symbol in extra:
            declaration = accepted[symbol]
            if declaration["kind"] == "presentation":
                raise InvalidIR("Dependent presentation reconstruction requires explicit local design")
            slots = SLOTS[declaration["kind"]]
            child["interfaces"][symbol] = {k: v for k, v in declaration.items() if k not in slots}
            pinned[symbol] = model.index[symbol]
            owners[symbol] = i
        retained.append(pinned)
    return retained
