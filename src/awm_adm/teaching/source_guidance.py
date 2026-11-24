"""Provider-facing source field explanations; not validators or normalizers."""

from ..temporal import INSTANT, SCOPE

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
ENTITIES = (
    "Stable entity identifiers, not display names: 1–128 ASCII characters, beginning with a letter "
    "or digit, followed by letters, digits, underscore, dot, colon or hyphen; no spaces. Preserve "
    "existing accepted identifiers. Distinct entities must not collapse onto the same identifier. "
    "Choosing an identifier does not change or resolve ambiguous entity meaning."
)
UNIT = (
    "Required nonempty unit, at most 100 characters, consistent with the supplied meaning and "
    "extracted facts. Use 'unitless' only for genuinely unitless predicates. Never fill an unknown "
    "physical unit or alter a numeric scale merely to satisfy the format."
)

SHARED = (
    "One shared evidence projection for the entire teaching plan, required when any child selects "
    "material; otherwise null. Children select their own material_ids and do not define projections. "
    "Represent all intended facts with compatible entities, predicates and time cells here, within "
    "the existing finite limits and source policy, at most 4096 entity-predicate-time combinations. "
    "A mapping is permitted coverage, not asserted "
    "facts: absent combinations remain unknown. Do not merge distinct entities or predicates, "
    "change units, bounds, dates, precision or claim meaning to make scopes compatible. If the "
    "requested meaning cannot share one supported projection, report unsupported with the concrete "
    "limit; ask a semantic question only when the user's meaning or a necessary choice is missing."
)

INSTRUCTIONS = (
    f"Source projection.namespace: {NAMESPACE} "
    f"Source projection.entities: {ENTITIES} "
    f"Each projection.predicates[].symbol: {SYMBOL} "
    f"Each predicate.kind: {KIND} "
    f"Each predicate.values: {VALUES} "
    f"Each predicate.unit: {UNIT} "
    f"Predicate bounds: {BOUNDS} "
    f"Time bounds: {INSTANT} {SCOPE} "
    "Representation bounds are not empirical limits. Retain justified or explicitly authorized bounds "
    "and units across replies; observed extrema alone do not authorize a carrier. Ask for a necessary "
    "modeling choice only when its meaning or authority is missing. "
)
