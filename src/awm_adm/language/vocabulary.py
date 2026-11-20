"""A revision-compatible view of historical language metadata, never model edits."""

from ..engine.errors import ADMError, ResourceLimit
from .models import Vocabulary
from .parser import Clarify, validate_vocabulary


def effective_vocabulary(model, metadata, budget):
    """Retain valid entries; never retarget an alias or change a supplied value.

    Stored profiles remain immutable. Explicit new profile installation continues
    to use strict validation. In particular an ambiguous alias loses its entire
    entry when any target disappears, rather than silently becoming unambiguous.
    """
    original = Vocabulary.model_validate(metadata).model_dump()
    result = Vocabulary().model_dump()
    omitted = []

    def keep(field, key, value, path):
        budget.tick()
        candidate = Vocabulary().model_dump()
        candidate[field] = {key: value}
        try:
            validate_vocabulary(model, candidate, budget)
        except ResourceLimit:
            raise
        except (ValueError, ADMError, Clarify):
            omitted.append(path)
            return False
        return True

    for alias, targets in original["aliases"].items():
        if keep("aliases", alias, targets, ["aliases", alias]):
            result["aliases"][alias] = targets
    for field in ("parameter_units", "parameter_roles", "value_aliases"):
        for symbol, parameters in original[field].items():
            for param, value in parameters.items():
                path = [field, symbol, param]
                if field == "value_aliases":
                    values = {
                        alias: item
                        for alias, item in value.items()
                        if keep(field, symbol, {param: {alias: item}}, [*path, alias])
                    }
                    if values:
                        result[field].setdefault(symbol, {})[param] = values
                elif keep(field, symbol, {param: value}, path):
                    result[field].setdefault(symbol, {})[param] = value
    validate_vocabulary(model, result, budget)
    return result, omitted
