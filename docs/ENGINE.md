# Finite engine and admission core

The local Python library in [`awm_adm.engine`](../src/awm_adm/engine/) supports empty/snapshot initialization, finite typed models, queries/plans, ordered admission, independent owner requirements, private construction and invariant certificates. The reusable core uses the Python standard library and has no HTTP, database or provider transport dependency.

The instance coordinator is in memory. It does not persist requests, run background acquisition, issue worker grants, or provide crash recovery. The [runtime](RUNTIME.md) persists initialized model snapshots and local operator runs, adds process ownership and uses a separate authenticated control listener. The [application API](API.md) provides durable public application requests and events; the [learning service](LEARNING.md) supplies durable background episodes and ordered admission. The status-only development server stays unready; the actual Docker runtime reports its component readiness. Ask/Teach translation and explanation, source extraction and managed intake are implemented by the services above this library.

## 1. Running and using the library

After [bootstrap](../README.md), run the complete offline example:

```sh
make engine-demo
```

It loads the authored tank fixture, computes and replays a shortest six-action plan, independently restores a snapshot, checks an unreachability certificate for a restricted action set, and exercises review plus forward receipt precedence from an empty instance. It makes no provider call. The script reports whether Lean ran; finite checking is always available.

Minimal domain-independent use:

```python
from awm_adm.engine import Instance, build_candidate

adm = Instance(mode="backward")  # initially empty
definitions = {
    "example.capacity": {
        "kind": "function", "params": {},
        "returns": {"kind": "int", "min": 0, "max": 100},
        "body": {"op": "literal", "value": 10},
    }
}
evidence = [{
    "artifact_kind": "evidence", "evidence_kind": "synthetic_fixture",
    "origin": "Owner-authored example", "scope": "Development example only",
    "content": {"description": "An explicitly supplied capacity"},
}]
package = build_candidate(adm.model, definitions,
                          candidate_id="capacity-1", evidence=evidence)
adm.receive(package)
adm.review("capacity-1", approve=True, expected_context=adm.context())
decision = adm.decide_next()
assert decision["status"] == "accepted"
answer = adm.query({
    "op": "evaluate", "module": "example",
    "expression": {"op": "call", "function": "example.capacity", "args": {}},
})
assert answer["status"] == "succeeded" and answer["value"] == 10
clone = Instance.restore(adm.export_snapshot(), mode="backward")
assert clone.instance_id != adm.instance_id
```

The example's domain definitions and evidence are caller data. The core does not contain a capacity rule or fixture-specific solution. Supplying a statement is not evidence that it is externally true.

`Instance.query` performs immediate local computation and retains a bounded result history. It accepts the supported typed query operations: capabilities, evaluate, check claim, find plan, check certificate and explain. It does not implement API submission/idempotency or durable pending work. A missing symbol returns `needs_input`; an exhausted check returns `inconclusive`, with no mathematical guarantee or invented learning job. Malformed query envelopes raise a typed validation error before execution. The application serving/learning orchestration preserves these distinctions.

## 2. Representation and stable identities

The following core profiles have stable byte encodings:

| Profile | Meaning |
| --- | --- |
| `finite-v0`, checker `adm-finite/0.1` | Closed finite typed declarations and checked executable theory root. |
| `adm-finite-table/0.1` | Exact finite states, transitions, labels, costs, goals and dependency-bound scope. |
| `adm-invariant/0.1` | Untrusted invariant-certificate data for a closed explicit action set. |
| `adm-result/0.1` | Semantic query/result binding, separate from execution identity. |
| `adm-conformance/0.1`, `/0.2` | Owner-supplied behavioral checks and optional independent invariants. |
| `adm-acquisition/1`, `adm-finite-proposal/2`, `adm-construction/1` | Task scope and structured acquisition/construction grammar. |

The engine's [`data.py`](../src/awm_adm/engine/data.py) retains canonical sorted finite encoding. The provider transport encoder is separate. Provider schemas retain authored property order via `encode_wire`; canonical schema hashes and ordered-wire hashes remain distinct. Golden tests compare **exact stored artifact bytes**, declaration roots, model roots, transition-table digests, prompts and both schema encodings to archived reference-engine fixtures.

Finite types include bounded integers, booleans, enums, records, sums, vectors and refinements. Pure expressions and finite quantifiers define functions, transitions, goals and checked assertions. Product, coproduct, pullback and equalizer presentations receive their original finite checks. Recursion, host code, unspecified values, arbitrary theorem source and unsupported syntax fail explicitly. Only a fully checked model is executable. Returned public model metadata is copied; private implementation fields are not an authority boundary against a hostile Python caller.

The finite representations and algorithms are implemented in [`engine/`](../src/awm_adm/engine/). Compatibility fixtures are contained in this repository; no parent source is a runtime or test dependency.

## 3. Instance ownership and publication

[`Instance`](../src/awm_adm/engine/instance.py) owns checked versions, current mode, owner policy and epoch, evidence support, candidate receipts, optional imported state, lineage and local results. Its explicit context contains instance identity, executable root, policy epoch and support root. Same-content learning can update evidence support without changing the executable root.

| Operation | Local contract |
| --- | --- |
| `receive(package)` | Check exact bytes/attachment integrity, then assign a monotonic instance-local receipt sequence. Repeating identical content is idempotent; changed content/review policy under the same candidate ID conflicts. |
| `review(..., expected_context=...)` | Owner approval or decline, tied to the current theory, support and epoch. Approval permits checking; it does not bypass admission. |
| `decide_next()` | Consider only the earliest undecided receipt. A head awaiting review blocks later admission. One validator runs per instance; other local queries continue. |
| `set_mode(...)` | Change future conflict decisions and increment the epoch. Historical decisions remain unchanged. |
| `set_conformance(...)` | Validate independently supplied requirements against current content; publish only if the captured context is still current. |
| `query(...)` | Pin a checked model/support/epoch, compute outside the publication lock, validate the result binding and retain an independent attempt/result identity. |

Receipt order is established at the local integrity-checked receipt boundary, not by source dates, generation start times or wall-clock tie breaking. A review hold never assigns a new receipt number. `review_required=False` is an explicit **owner/library** option for checked automatic admission; provider-produced data cannot set it. Workers will not receive an `Instance` handle.

Forward mode prefers later admissible conflicting results; backward mode rejects the entire conflicting batch. Both enforce type/finite checks, explicit dependencies, observation checks and all applicable owner requirements. Replacement removes dependent declarations unless the candidate supplies valid replacements. Stale external dependencies and retractions of superseded content fail explicitly; independent additions may reconcile from an older retained base.

Validation and owner checks run outside the short publication lock. The final publication requires unchanged theory/support/epoch. A changed context discards staged validation; review approval must be refreshed, and automatic candidates must be checked again. Publication prepares the entire model/support/decision before changing active state. An interrupted checker, storage-cap failure or injected preparation failure cannot expose a partial theory. These are library guarantees. Runtime/application transactions and leases cover initialized models, owner edits, request results and durable candidate publication. The learning coordinator commits accepted theory, support, decision and request wakeups together in the receiving ADM database.

The default library caps retain 128 theory versions, 1,000 candidate records, 1,000 query results and a 64 MiB allowance for retained artifact/payload bytes. These finite local caps stop with explicit exhaustion; there is no silent history pruning or automatic budget expansion. A decision whose audit record cannot fit leaves its receipt pending and the accepted state unchanged. The caps are not a measurement of Python heap usage or a hard operating-system memory limit. Deployment queues and storage accounting use finite service configuration; the [operations contract](OPERATIONS.md) defines recovery, diagnostics and explicit event pruning while preserving evidence and idempotency under finite caps.

## 4. Owner requirements and evidence

[`conformance.py`](../src/awm_adm/engine/conformance.py) checks independently installed finite behavior, interfaces and `/0.2` invariants. Required symbols may be dormant in an empty instance. Once activated, removal of required declarations cannot make the checks disappear. An invariant's `module_all` selection includes future learned actions; explicit selection stays closed. Owner carriers and predicates cannot depend on learned definitions that shrink the protected domain.

Candidate assertions and supplied observations are checked, but cannot modify the owner policy. Both modes reject a nonconforming candidate. Policy-free instances report `not_configured` and make no domain-conformance claim.

Each accepted declaration's origin preserves exactly the evidence subset in its wrapper. Batch decisions retain the complete checked evidence set. Unaffected origins remain unchanged; replacement removes retired support from the active export closure. Same-content acceptance can record new support with an unchanged theory root. Historical query results keep the original support and theory identities.

## 5. Local plans, results and proofs

[`planning.py`](../src/awm_adm/engine/planning.py) retains bounded breadth-first search and witness replay. Results distinguish a valid witness, shortest action count, exhaustion of a depth bound, exhaustion of the reachable graph and resource exhaustion. Adding a new action can preserve an old witness while invalidating its old module-wide minimum. Original `module_all` intent is retained independently of an explicit list, including `[]`.

Core semantic bindings identify the exact root, normalized query and resolved scope. The instance adds request, attempt and result identities plus pinned policy/support context. A wrong query, root or binding digest cannot enter the local result history. Different resource budgets can produce the same semantic binding but distinct execution attempts. A query already running remains pinned when another thread publishes a new model.

[`certificates.py`](../src/awm_adm/engine/certificates.py) reconstructs the executable transition table on every check. An old certificate fails against a changed theory, even when an old witness remains valid. The generated Lean backend checks only owned templates with bounded numeric data; it accepts no caller-supplied Lean source or imported proof status.

For real Lean verification, configure a trusted absolute Lean **4.19.0** executable:

```sh
export AWM_ADM_LEAN="/absolute/path/to/lean-4.19.0/bin/lean"
make check-lean
make engine-demo
make check
make isolate
```

AWM-ADM uses `AWM_ADM_LEAN`; it does not inherit a different application's compiler environment. `LeanBackend(path)` also accepts explicit operator configuration. `Instance.query(..., lean=backend)` passes that trusted object separately from query data. No compiler is downloaded during serving. Missing/wrong Lean is explicit and never silently downgraded. Ordinary tests report real-kernel skips without the environment variable; those skips do not satisfy real-kernel verification.

Reports keep **`lean_kernel`** proof checking separate from **`exhaustive_finite`** correspondence to executable IR. Python evaluation, finite enumeration, translation and the configured compiler remain trusted implementation code. Finite lifecycle traces do not constitute a proof of this implementation.

## 6. Acquisition without a running learner

The shared acquisition interface uses model-neutral prompts and structured grammars. They explain learning, executable definitions and local admission on the first attempt, preserve source provenance and do not branch by provider/model name. Tests compare their canonical and ordered-wire identities to compatibility fixtures and exercise schema-local recursive decoding.

[`construction.py`](../src/awm_adm/engine/construction.py) seeds receiver-owned interfaces, merges bounded updates into private drafts and checks completeness. Drafts are data, never active `Model` objects. Tests use authored missing/bad/revised definitions, including a complete but owner-incompatible candidate. They are controlled tests, not live repair or acquisition-reliability measurements. The learning service wraps this core with durable episodes, versioned provider transports, explicit budgeted dispatch and ordered publication.

## 7. Model snapshots

AWM-ADM imports the legacy `adm/0.1` model format `0.1` and exports the versioned `awm-adm/2` model format **`2.0`**. Both retain the original finite artifacts. AWM-ADM exports always include the actual owner-policy profile, including empty or dormant `/0.2` policies. Legacy snapshots without a policy restore with the explicit empty legacy policy; absent metadata is not reconstructed by guessing.

An export captures one model/support/policy/lineage view under the lock, then checks and packages it outside the lock. It contains only the necessary artifact closure, exact origins/evidence, admission provenance, policy and optional explicitly typed state. Active proof status, candidate queues, query history, provider configuration, grants, credentials and process authority are excluded. Archive writing validates first and publishes exclusively; existing destinations are not overwritten.

Restore checks bounded uncompressed archive members, paths, lengths, hashes, profile negotiation and closure, then re-admits the executable theory, rechecks owner requirements and validates state locally. Historical reports do not confer authority. A new instance receives a fresh identity, epoch and receipt sequence; imported premises form its initial baseline. Source receipt numbers remain provenance. A restored state remains pinned to its original interpretation and cannot silently be re-exported under another root.

The reference tests import **stored reference-engine archives** for empty, tank, access and learned-policy instances. They also exercise corrupted bytes, missing evidence, incompatible policies, bad state with recomputed hashes, unsupported profiles, archive traversal/symlinks, resource exhaustion, deterministic export and independent histories. Reference-engine databases are not opened or migrated by AWM-ADM.

## 8. Scope

The finite core now supports the [Docker runtime](RUNTIME.md), with persistent initialization, local run recovery and Linux ARM64 Lean checks. The [application API](API.md) supplies public asynchronous requests and events. The console and supervised learning use those durable services. These services do not establish autonomous discovery, general theorem proving, external truth, long-running reliability or clustered Byzantine safety.
