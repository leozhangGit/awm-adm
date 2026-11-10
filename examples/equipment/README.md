# Shared equipment checkout fixture

Synthetic, owner-authored instance data for [teaching and local verification](../../docs/TEACHING.md). The truth table and history expectations are independent test inputs; no provider response generated these files.

- `requirements.json`: independent nine-case borrowing truth table.
- `task.json`: model-neutral acquisition task and receiver-owned interface; no implementation body.
- `authored-model.json` / `authored-snapshot.adm`: expected local model and recheckable snapshot for offline/import checks.
- `recorded-acquisition.json`: explicitly authored construction response for simulated preparation only.
- `expected.json`: independent local/translation/history expectations.
- `source-policy.json`: finite entity, predicate, value carrier, year cells and source authority. External disclosure starts disabled.
- `history-*.json`: structured historical inputs, conflict and correction controls.
- `history-2026.txt`: synthetic prose for a separately authorized extraction call.

The rule advises on supplied `borrowed` and `available` counts. It neither maintains current inventory nor executes checkout. Historical capacity is a separate, source-bound fact; accepting it does not rewrite the rule. Do not describe recorded rehearsal as autonomous discovery or live reliability evidence.
