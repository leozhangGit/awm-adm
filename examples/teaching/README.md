# Conversational equipment checkout fixture

Synthetic, owner-authored material for a conversational teaching walkthrough. It is instance data, never engine or shared provider guidance.

- `teach.txt`: the ordinary-language teaching request.
- `history.md`: the attachment disclosed to the provider after explicit consent.
- `requirements.json`: nine independent borrowing checks, installed before acquisition; provider output cannot amend them.
- `expected.json`: independent borrowing and historical outcomes.
- `provenance.json`: hashes and provenance of the underlying equipment fixture expectations.

Borrowing is advisory: return true precisely when borrowed < 2 and available ≥ 1, over integer inputs 0–2. It performs no checkout and does not infer current inventory from historical capacity. Camera-kit capacity is 2 in 2025, 1 in 2026, unknown from 2027. Intervals are half-open UTC years.

`tests/test_teaching_journey.py` supplies authored simulated responses through the real workflow. Its success verifies plumbing and checks, not live provider understanding. See the [teaching guide](../../docs/TEACHING.md) for preparation, execution and review boundaries. Any live provider call requires explicit scope and budgets.
