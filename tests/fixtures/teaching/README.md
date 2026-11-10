# Teaching preparation regression fixtures

`malformed-legacy-reply.json` is the exact visible response text from a bounded synthetic-equipment live preparation call. It contains only the approved synthetic equipment fixture and reference IDs; no credential or hidden reasoning content.

The outer reply is valid JSON. Its `plan_json` string lacks the final closing brace. The strict legacy decoder must reject it at character offset 4870. The native decoder must reject the legacy envelope rather than selecting a fallback from provider-controlled content. Tests never repair or admit this response or perform a remote retry. The original trial artifact remains immutable.

`invalid-native-source-reply.json` is the exact visible text of the second live preparation response, retained without reformatting from its visible response text. SHA-256: `22266fe23b03626bbbfa2bcaa5663f7e670669a6ccddc373888bdcc795d7a43f`.

Its bare predicate `capacity` violates the qualified-symbol contract. After changing only that field in an authored offline control, the integer predicate's `values: ["0", "1", "2"]` still fails: only enums have named values. Tests reject the original response and either one-field change. A separate authored two-field control passes preparation only. No fixture is repaired in place, replayed to a live provider, admitted or counted as a live repair result. Additional boolean/enum/boundary controls exercise the same unchanged local validators. The fixture contains approved synthetic data and reference IDs only, without credentials or hidden reasoning.
