"""Historical price-profile decoding; these records do not gate new dispatch."""

import pytest

from awm_adm.allowances.pricing import amount, check_wire, profile
from awm_adm.providers.wire import make_wire, specification
from awm_adm.runtime.protocol import RuntimeFault, dumps, loads

from .test_application import app_runtime as app_runtime
from .test_learning_service import rig as rig

PROFILE = "openai-5.6-luna-context/2026-11-09"
RATES = {
    "bound_profile": PROFILE,
    "input_micro_usd_per_million": 500_000,
    "output_micro_usd_per_million": 1_800_000,
}


@pytest.mark.parametrize(
    "changes", [{"input_micro_usd_per_million": 499_999}, {"output_micro_usd_per_million": 1_799_999}]
)
def test_luna_long_context_and_cache_write_rates_cannot_be_understated(changes):
    with pytest.raises(RuntimeFault, match="No verified"):
        profile({**RATES, **changes}, {"provider": "openai", "model": "gpt-5.6-luna"})


def test_luna_profile_covers_full_context_and_excludes_extra_billing():
    c = {"provider": "openai", "model": "gpt-5.6-luna", "capabilities": ["json_schema"]}
    bound = profile(RATES, c)
    assert bound["input_bound"] == 1_050_000 and not bound["synthetic"]
    assert amount(1_050_000, 8192, RATES) == 539746
    wire, _ = make_wire(c, specification(connection_test=True), 8192)
    check_wire(wire, c, bound, 8192)
    for key, value in (("prompt_cache_options", {"ttl": "12h"}), ("tools", []), ("service_tier", "priority")):
        with pytest.raises(RuntimeFault, match="without tools"):
            check_wire(dumps({**loads(wire), key: value}), c, bound, 8192)
    with pytest.raises(RuntimeFault, match="No verified"):
        profile(RATES, {**c, "model": "unreviewed-alias"})
