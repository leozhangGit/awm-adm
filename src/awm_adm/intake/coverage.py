"""Additive coverage proposals preserve every accepted carrier and time cell."""

from ..learning.service import fault, fingerprint
from ..sources.models import Projection


def extend(current, proposed):
    from ..temporal_evidence.legacy import extend as temporal_extend
    from ..temporal_evidence.legacy import is_catalog

    if is_catalog(current) or is_catalog(proposed):
        return temporal_extend(current, proposed)
    if not current or current == proposed:
        return proposed
    if current["namespace"] != proposed["namespace"]:
        fault("needs_specification", "Use the existing source namespace, or another model for this material")
    predicates = {p["symbol"]: p for p in current["predicates"]}
    for predicate in proposed["predicates"]:
        prior = predicates.get(predicate["symbol"])
        if prior and prior != predicate:
            fault(
                "needs_specification",
                "The supplied fact changes an existing unit or value range. Clarify the intended predicate before learning",
            )
        predicates[predicate["symbol"]] = predicate
    cells = {fingerprint(c): c for c in [*current["cells"], *proposed["cells"]]}
    try:
        merged = Projection.model_validate(
            {
                **current,
                "entities": list(dict.fromkeys([*current["entities"], *proposed["entities"]])),
                "predicates": list(predicates.values()),
                "cells": sorted(cells.values(), key=lambda c: c["effective_from"]),
            }
        ).model_dump()
    except ValueError:
        fault(
            "needs_specification",
            "The new dates overlap existing intervals or change their time unit. Clarify the time coverage before learning",
        )
    if len(merged["entities"]) * len(merged["predicates"]) * len(merged["cells"]) > 4096:
        fault("resource_exhausted", "Combined source coverage exceeds the finite projection limit")
    return merged
