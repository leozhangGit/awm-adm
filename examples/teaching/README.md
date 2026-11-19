# Conversational equipment checkout fixture

Synthetic, owner-authored material for a conversational teaching walkthrough. It is instance data, never engine or shared provider guidance.

- `teach.txt`: the ordinary-language teaching request.
- `history.md`: the attachment selected and submitted with the teaching request, authorizing its bounded provider disclosure.
- `requirements.json`: nine optional independent borrowing checks. The automated fixture installs them before acquisition; provider output cannot amend them. Normal Teach does not require this separate setup.
- `expected.json`: independent borrowing and historical outcomes.
- `provenance.json`: hashes and provenance of the underlying equipment fixture expectations.

Borrowing is advisory: return true precisely when borrowed < 2 and available ≥ 1, over integer inputs 0–2. It performs no checkout and does not infer current inventory from historical capacity. Camera-kit capacity is 2 in 2025, 1 in 2026, unknown from 2027. Intervals are half-open UTC years.

`tests/test_teaching_journey.py` supplies authored simulated responses through the real workflow. Its success verifies plumbing and checks, not live provider understanding. See the [teaching guide](../../docs/TEACHING.md) for automatic preparation, checked execution and clarification when needed. An engineering live trial requires explicit scope and test budgets; ordinary Teach uses the enabled connection without spending forms.
