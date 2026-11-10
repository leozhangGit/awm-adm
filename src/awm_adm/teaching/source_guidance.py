"""Provider-facing source field explanations; not validators or normalizers."""

NAMESPACE = (
    "Projection namespace. This does not automatically prefix predicate symbols; "
    "each predicate must carry its complete qualified symbol."
)
SYMBOL = (
    "Complete qualified predicate symbol, for example domain.measure, not a bare measure name. "
    "Use at least two dot-separated identifier segments; each starts with an ASCII letter or "
    "underscore and continues with ASCII letters, digits or underscores. Maximum 200 characters. "
    "Preserve an existing predicate's exact symbol when supplied."
)
KIND = (
    "Source predicate kind: boolean, integer or enum. These spellings differ from the bool/int "
    "kinds in plan.types. Integer bounds define a numeric carrier, not string enum labels."
)
VALUES = (
    "For boolean and integer predicates, values must be []. For enum predicates only, provide "
    "a nonempty array of unique, nonempty string labels. These are the permitted carrier labels, "
    "not observations or a list of numeric bounds converted to strings."
)
BOUNDS = (
    "minimum and maximum are integer fields. For integer predicates they are the inclusive "
    "carrier bounds. Always keep minimum <= maximum, a span <= 1000000 and both within "
    "[-9007199254740991, 9007199254740991]; for boolean/enum use 0 and 100 when unused."
)

INSTRUCTIONS = (
    f"Source projection.namespace: {NAMESPACE} "
    f"Each projection.predicates[].symbol: {SYMBOL} "
    f"Each predicate.kind: {KIND} "
    f"Each predicate.values: {VALUES} "
    f"Predicate bounds: {BOUNDS} "
)
