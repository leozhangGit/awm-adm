"""Historical language metadata cannot change meaning or block current catalogs."""

from copy import deepcopy

import pytest

from awm_adm.engine import Budget, Instance
from awm_adm.engine.errors import ResourceLimit
from awm_adm.language.models import Vocabulary
from awm_adm.language.parser import validate_vocabulary
from awm_adm.language.vocabulary import effective_vocabulary

from .ported.helpers import BOOL, function, integer, literal


def model():
    return Instance(
        {
            "profile": "finite-v0",
            "declarations": {
                "sensor.reading": function({"n": integer(0, 2)}, BOOL, literal(True)),
                "sensor.flag": function({}, BOOL, literal(True)),
            },
        }
    ).model


def test_removal_drops_whole_ambiguous_alias_and_only_invalid_parameter_values():
    raw = Vocabulary(
        aliases={
            "reading": ["sensor.reading"],
            "pick": ["sensor.flag", "gone.flag"],
            "old": ["gone.flag"],
            "sensor.flag": ["sensor.reading"],
        },
        parameter_units={"sensor.reading": {"n": "units", "removed": "units"}, "gone.flag": {"n": "units"}},
        parameter_roles={"sensor.reading": {"n": "value"}},
        value_aliases={"sensor.reading": {"n": {"one": 1, "out_of_range": 3, "1": 2}}},
    ).model_dump()
    saved = deepcopy(raw)
    effective, omissions = effective_vocabulary(model(), raw, Budget())
    assert (
        effective
        == Vocabulary(
            aliases={"reading": ["sensor.reading"]},
            parameter_units={"sensor.reading": {"n": "units"}},
            parameter_roles={"sensor.reading": {"n": "value"}},
            value_aliases={"sensor.reading": {"n": {"one": 1, "1": 2}}},
        ).model_dump()
    )
    assert ["aliases", "pick"] in omissions
    assert ["value_aliases", "sensor.reading", "n", "out_of_range"] in omissions
    assert raw == saved
    with pytest.raises(ValueError):
        validate_vocabulary(model(), raw, Budget())  # New writes remain strict.
    assert effective_vocabulary(model(), effective, Budget()) == (effective, [])


def test_budget_exhaustion_is_not_silently_treated_as_obsolete_metadata():
    with pytest.raises(ResourceLimit):
        effective_vocabulary(model(), {"aliases": {"reading": ["sensor.reading"]}}, Budget(1, 5))
