"""Provider-independent guidance for the closed temporal evidence contract."""

EXACT_TIME = (
    "Decide whether the source names one exact clock instant or an uncertain occurrence window. "
    "For kind instant (or an exact time anchor), use precision second and effective_to null. "
    "Second is the supported coordinate resolution for that exact instant, not a claim about "
    "instrument accuracy. Do not choose hour/minute precision merely because lower clock "
    "components are omitted from a uniquely specified clock time. An approximate or rounded "
    "observation time must instead retain its supported occurrence window and precision; never "
    "invent a precise instant or window bounds. Clarify genuinely missing temporal meaning."
)

SCOPE_KIND = (
    "instant names one exact instant; occurrence means somewhere in a bounded window; validity "
    "holds throughout a bounded interval; period_value describes the entire period, not every instant."
)
TIME_BOUND = "Canonical UTC timestamp YYYY-MM-DDTHH:MM:SSZ for a supported bound; never a date-only value."
END_BOUND = (
    "Null only for an instant. Otherwise the supported exclusive end, strictly later than "
    "effective_from, in canonical UTC seconds. Never invent an end to satisfy the format."
)
ZONE = (
    "Captured IANA timezone name (UTC is allowed). Use the relevant explicit source/user zone, "
    "otherwise the supplied system default. UTC encoding of bounds does not change this provenance. "
    "legacy_unrecorded is reserved for retained legacy compatibility metadata."
)


def describe_scope(node, *, anchor=False):
    """Annotate a newly generated wire schema; never validate or transform values."""
    fields = node["properties"]
    fields["kind"]["description"] = (
        "exact names one instant; window bounds an uncertain occurrence; unknown has all other fields null."
        if anchor
        else SCOPE_KIND
    )
    fields["effective_from"]["description"] = TIME_BOUND + (
        " Null only when kind is unknown." if anchor else ""
    )
    fields["effective_to"]["description"] = (
        "For exact/unknown use null. A window has a supported exclusive end strictly after its start. "
        + TIME_BOUND
        if anchor
        else END_BOUND
    )
    fields["precision"]["description"] = EXACT_TIME + (
        " Unknown anchors use null. Windows retain their supported precision."
        if anchor
        else " Windows/intervals retain their supported precision. legacy is compatibility metadata, not a new observation."
    )
    fields["timezone_basis"]["description"] = (
        "Unknown anchors use null. Otherwise use the explicit relevant source/user IANA zone or supplied system default."
        if anchor
        else ZONE
    )


INSTRUCTIONS = (
    """Prepare one plan.evidence_scope catalog shared by all source children.
It has profile awm-adm-temporal-catalog/1, a finite namespace, entities, predicate
series and cells. It contains no asserted values. Propose only the mapping needed for this request;
omitting unrelated accepted descriptors does not remove them from the accumulated catalog.
The request mapping has at most 32 predicates and 4096 possible addresses; the
accumulated sparse catalog has a separate 65536-predicate ceiling. An accepted
catalog view may be explicitly partial. Absence from that view is not proof that
a property is new; clarify uncertain identity instead of creating a synonym.
Reuse accepted predicate symbols
and their exact meanings, carriers, units, qualifiers, statement levels and metric.
A new unrelated predicate needs its own explicit meaning. Never rename a conflicting
property, vary qualifiers or choose a new namespace merely to bypass its identity.
Predicate kinds remain boolean, integer or enum. Use exact supplied units, explicit
finite integer bounds with width at most 1000000, or finite enum values. Boolean
and integer predicates have values []; only enum has nonempty unique values.
Each predicates[].symbol must be a complete qualified symbol with at least two
dot-separated identifier segments, such as domain.measure. Each segment starts with
an ASCII letter or underscore and continues with ASCII letters, digits or underscores.
The catalog namespace does not automatically prefix symbols. Entity identifiers
are separate stable names, never nested objects or executable expressions.

Cells can coexist with different kinds: instant is an exact second with no end;
validity means a value holds throughout [effective_from,effective_to); period_value
means a value for that period as a whole, not at each instant; occurrence means an
observation happened somewhere within a known window. A date-only
occurrence is not midnight and is not whole-day validity. Use supported UTC seconds
and preserve timezone_basis and the source's temporal meaning. Use the supplied system timezone
unless a relevant explicit source/user zone overrides it. Do not invent subsecond
precision, stretch an instant, split/merge an accepted validity scope, prorate a period
or infer periods outside evidence. A period_value series requires metric semantics;
other series have metric null. scope_kinds declares supported forms for that property.
Legacy compatible_catalog cells may carry legacy precision; preserve their identity
when extending coverage, but new extracted observations use their actual precision.

statement_level direct asserts the subject's value. It has actor and modality null.
statement_level reported asserts that an identified actor made a statement; it requires
actor and modality and preserves the report occurrence separately from the target
period. A forecast/report is not its realized outcome. Represent only finite explicit
propositions, never convert arbitrary quotation/negation/hypothetical text into facts.
Missing meaning requires clarification or unsupported, not fabricated semantics.

At most 128 entities, 32 series, 256 temporal cells and 4096 combined addresses across
the catalog. Do not create separate source children just because time kinds differ.
Select material.material_ids from material_manifest.entries[].id; never supply or ask
for source/item/version IDs, evidence groups, permissions or partition IDs. Preserve
all relevant input_ids. Select originals containing observations or explicitly adopted
model premises with their scope, including earlier originals across clarifications;
instructions and bounds-only replies alone are not facts.
A child may use both messages and uploads. Citation links are attribution, not fetched
or independently verified content. Queue entries describe future push scope only.
"""
    + EXACT_TIME
)

# Retained reply profiles keep INSTRUCTIONS byte-for-byte. Fresh preparation
# makes the information/capability distinction explicit in both prompt and wire.
ASSESSED_PREPARATION = INSTRUCTIONS.replace(
    "Missing meaning requires clarification or unsupported, not fabricated semantics.",
    "Missing meaning requires an information-gap question, not an unsupported capability. "
    "Only an actual contract limit belongs in unsupported_capabilities; never fabricate semantics.",
)

EXTRACTION = (
    """Extract proposals under the supplied typed temporal catalog. Use exact predicate
identities, carriers, units and scope kinds. Preserve direct versus reported meaning;
assertion_kind assertion is permitted for a reported series only when the source
explicitly supports the attributed report, never as a conversion to external truth.
Keep subject scope, observed_time and reported_time distinct. Missing anchors are
kind unknown with all remaining fields null. Exact anchors have second precision
and no end; imprecise anchors are bounded windows. Receipt time supplies neither.
Follow the catalog's actual subject: an event's occurrence scope describes the
event, while observed_time describes its observation/inspection. A source-backed
subject claim is not automatically an observation that a reader read the source.
Never repair a mistaken catalog by changing its subject during extraction. Keep
unsupported subject mappings unresolved. Preserve a supplied calculation as such;
extraction is not a new execution or proof of that calculation.
New facts must not author legacy precision. An occurrence_id is only an identifier
explicitly supported by the original for that event, otherwise null. Never fabricate
an event ID to turn uncertain occurrences into simultaneous claims. Preserve UTF-8
byte spans into original content. Do not round, aggregate, extrapolate or infer a
value merely from catalog coverage. Return only the requested closed claim schema.
"""
    + EXACT_TIME
)

ASK = (
    """For typed temporal catalog metadata use this additional command:
query evidence with {"op":"query_evidence","intent":INTENT,"entity_id":ENTITY,
"predicate":PREDICATE,"scope":SCOPE,"reported_time":null,"relation":"contained",
"limit":100,"cursor":null}
SCOPE has kind, effective_from, effective_to, precision and timezone_basis. Use
value_at with instant; value_throughout with validity; value_for_period with
period_value for an exact target period; observations_in for observations within a
bounded window; reports_about for attributed statements about a subject period.
A collection is not a scalar. Select the intended accepted predicate and preserve
its metric, actor/modality and qualifiers. Do not silently pick a latest forecast.
reported_time can explicitly select an exact/window report anchor; null adds no filter.
Unknown time cannot be a filter. For occurrence searches possibly_overlapping includes
uncertain overlaps and must be described as such; contained requires full containment.
Never turn a period total into an instant or a point into a whole-period value.
For a user-supplied calendar date you may provide scope instead as
{"kind":KIND,"effective_on":"YYYY-MM-DD","timezone":null}; the application resolves
the entire civil day using its supplied system timezone (or the explicit relevant zone).
This short form cannot denote an exact instant. Never ask for timezone just to fill
an internal field. Metadata gives permitted meanings, not observed values or truth.
"""
    + EXACT_TIME
)

RECALL = """
For recalling saved evidence without a user-requested time filter, use:
recall evidence with {"op":"recall_evidence","selectors":[{"entity_id":ENTITY,
"predicate":PREDICATE}],"limit":100,"cursor":null}
Select 1–32 exact, distinct entity/predicate pairs from the disclosed catalogs.
This bounded local read returns accepted records with their own subject scopes,
typed values/units, attribution and source references. It does not require a time
window from the user, does not choose the latest record and does not compute a
new difference, total or consequence. Use it when the question asks what is saved,
when a recorded event occurred or what an earlier calculation recorded. Use an
executable definition for a requested new computation, when one exists.
For an explicit temporal condition use the corresponding time-filtered query;
do not drop that condition by choosing recall. Distinguish event/subject time
from when a source was inspected or a calculation recorded. Do not invent a scope
or ask for a storage/inspection date just to fill a query field.
Multiple supporting sources do not alone require a source-choice question. Include
the relevant pairs; the local records retain their differences. Clarify genuinely
ambiguous subjects/properties or choices material to the requested answer. Never
guess a value from catalog meanings, collapse different reports into one truth,
select an arbitrary latest value or treat matching words as semantic equivalence.
Existing observation-only records remain observations; recall does not promote
their descriptive text to a newly checked typed subject value. Empty/incomplete
results and conflicting records must remain explicit.
"""
