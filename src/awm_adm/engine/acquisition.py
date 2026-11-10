"""Task-owned acquisition scope; independent of a provider's proposed theory."""

from .data import MAX_BYTES, encode, name, read_json, shape, thaw
from .errors import InvalidIR
from .model import declaration_references

PROFILE = "adm-acquisition/1"
DEFAULT_CONTRACT = {
    "profile": PROFILE,
    "required_symbols": [],
    "allowed_helpers": None,
    "interfaces": {},
    "allowed_retractions": None,
    "max_declarations": 64,
    "max_bytes": 131072,
}


class AcquisitionError(InvalidIR):
    code = "acquisition_contract"


def validate_contract(source=None):
    contract = thaw(read_json(DEFAULT_CONTRACT if source is None else source))
    shape(contract, tuple(DEFAULT_CONTRACT))
    if contract["profile"] != PROFILE:
        raise InvalidIR("Unsupported acquisition contract profile")
    for field in ("required_symbols", "allowed_helpers", "allowed_retractions"):
        values = contract[field]
        if field in ("allowed_helpers", "allowed_retractions") and values is None:
            continue  # Bounded exploratory tasks need not know future symbol names.
        if not isinstance(values, list) or len(values) > 256:
            raise InvalidIR("Acquisition symbol list must contain at most 256 names", field=field)
        for symbol in values:
            name(symbol, qualified=True)
        if len(values) != len(set(values)):
            raise InvalidIR("Duplicate acquisition symbol", field=field)
    required = set(contract["required_symbols"])
    helpers = set(contract["allowed_helpers"] or [])
    if required & helpers or required & set(contract["allowed_retractions"] or []):
        raise InvalidIR("Required, helper and retracted symbols must have distinct roles")
    for field, maximum in (("max_declarations", 256), ("max_bytes", MAX_BYTES)):
        if type(contract[field]) is not int or not 1 <= contract[field] <= maximum:
            raise InvalidIR("Invalid acquisition limit", field=field)
    if len(required) > contract["max_declarations"]:
        raise InvalidIR("Acquisition declaration limit is smaller than its required scope")
    interfaces = contract["interfaces"]
    if not isinstance(interfaces, dict) or set(interfaces) - required:
        raise InvalidIR("Acquisition interfaces must describe required symbols")
    for symbol, interface in interfaces.items():
        if (
            not isinstance(interface, dict)
            or "kind" not in interface
            or set(interface) & {"body", "legal", "next", "cost"}
        ):
            raise InvalidIR(
                "Acquisition interfaces contain metadata, not executable definitions", symbol=symbol
            )
    return contract


def task_contract(task):
    return validate_contract(task.get("acquisition_contract"))


def check_size(source, contract):
    data = source.encode("utf-8") if isinstance(source, str) else source
    if not isinstance(data, bytes):
        data = encode(read_json(data))
    if len(data) > contract["max_bytes"]:
        raise AcquisitionError("Proposal exceeds acquisition byte limit", limit=contract["max_bytes"])


def check_proposal(declarations, retractions, contract, budget, *, complete=True):
    """Check a complete normalized change before packaging or receipt."""
    if not isinstance(declarations, dict) or not isinstance(retractions, list):
        raise AcquisitionError("Acquisition requires declaration and retraction containers")
    check_size({"declarations": declarations, "retractions": retractions}, contract)
    if len(declarations) > contract["max_declarations"]:
        raise AcquisitionError("Too many proposed declarations", limit=contract["max_declarations"])
    retraction_limit = (
        len(contract["allowed_retractions"]) if contract["allowed_retractions"] is not None else 64
    )
    if len(retractions) > retraction_limit:
        raise AcquisitionError("Too many proposed retractions", limit=retraction_limit)
    for symbol in [*declarations, *retractions]:
        budget.tick()
        name(symbol, qualified=True)
    if len(retractions) != len(set(retractions)) or set(retractions) & declarations.keys():
        raise AcquisitionError("Duplicate or simultaneously replaced retraction")
    missing = set(contract["required_symbols"]) - declarations.keys()
    if missing and complete:
        raise AcquisitionError("Required declarations are missing", missing_symbols=sorted(missing))
    helpers = set(declarations) - set(contract["required_symbols"])
    allowed = contract["allowed_helpers"]
    if allowed is not None and helpers - set(allowed):
        raise AcquisitionError(
            "Unrequested declarations are outside acquisition scope", symbols=sorted(helpers - set(allowed))
        )
    if contract["allowed_retractions"] is not None and set(retractions) - set(
        contract["allowed_retractions"]
    ):
        raise AcquisitionError(
            "Retractions are outside acquisition scope",
            symbols=sorted(set(retractions) - set(contract["allowed_retractions"] or [])),
        )
    for symbol, expected in contract["interfaces"].items():
        budget.tick()
        if symbol not in declarations and not complete:
            continue
        body = declarations[symbol]
        if not isinstance(body, dict):
            raise AcquisitionError("Declaration must be an object", symbol=symbol)
        actual = {k: v for k, v in body.items() if k not in ("body", "legal", "next", "cost")}
        if encode(actual) != encode(expected):
            raise AcquisitionError(
                "Requested interface differs", symbol=symbol, expected=expected, actual=actual
            )
    if complete and contract["required_symbols"]:
        reachable, pending = set(), list(contract["required_symbols"])
        while pending:
            budget.tick()
            symbol = pending.pop()
            if symbol in reachable:
                continue
            reachable.add(symbol)
            if symbol in declarations:
                pending.extend(declaration_references(declarations[symbol]) - reachable)
        if helpers - reachable:
            raise AcquisitionError(
                "Helper declarations must support requested definitions", symbols=sorted(helpers - reachable)
            )
