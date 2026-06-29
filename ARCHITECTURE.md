# solve architecture

`solve` is the scale experiment for the Manifold Destiny architecture.

It points verifier-mediated bounded generation at a real verified corpus: mathlib.
The goal is to test whether the self-extending grammar can produce verified Lean
theorems that are not already in the imported library and survive a nontriviality
filter.

## 1. Trust boundary

The trusted path is:

```text
mathlib constants -> bounded grammar -> Lean kernel replay -> retained record
```

Everything else is advisory.

Language may propose.  
Language may rank.  
Language may explain.  
Language may configure.  
Language may not verify.  
Language may not retain truth.

Retention requires a replay receipt from Lean. A language model output is never a
proof, never a verifier, and never a retained theorem.

## 2. Core loop

```text
SEED -> CONSTRUCT -> VERIFY -> RETAIN -> PROMOTE -> MEASURE
```

### SEED

A bounded mathlib namespace supplies seed atoms. A seed atom is a theorem-like
Lean constant with:

- name
- type
- arity / binder shape
- conclusion head
- normalized statement hash
- imported module
- axioms used

The first experiments should use bounded imports, not `import Mathlib`.

### CONSTRUCT

Python owns orchestration and search policy. Lean owns truth.

The grammar is typed and operator-template based:

```text
Atom      := mathlib theorem | retained theorem
Candidate := Operator(parent_1, ..., parent_k)
depth     := 1 + max(parent depths)
```

Initial operator registry:

- equality / rewrite: `Eq.symm`, `Eq.trans`, `congrArg`, `congrFun`, tightly
  bounded `Eq.subst`
- iff: `Iff.intro`, `Iff.mp`, `Iff.mpr`
- structural controls: `And.intro`, `Or.inl`, `Or.inr`

The structural operators are useful controls because they generate many true but
usually uninteresting candidates. They should prove that the triviality filter
works, not be celebrated as discovery.

The generator should not emit arbitrary Lean syntax. Each operator has a Lean
template plus type constraints. Candidate formation is type-directed; Lean is the
final judge.

### VERIFY

Verification has two stages:

1. **Fast check** — elaborate candidate statement and proof term, infer the proof
   type, and require definitional equality with the candidate statement.
2. **Replay receipt** — render a real theorem into a generated Lean module and
   run `lake env lean` / Lean kernel replay.

Retention happens only after stage 2.

A long-running Lean worker is preferred once the smoke path works, because mathlib
imports are expensive. The worker should expose a small JSONL protocol:

```json
{"op":"health"}
{"op":"enumerate_atoms","imports":["Mathlib.Data.List.Basic"],"prefixes":["List"]}
{"op":"verify","candidate":{}}
{"op":"defeq","left":"...","right":"..."}
{"op":"normalize","statement":"..."}
```

### RETAIN

A retained record must include:

- experiment id
- toolchain and mathlib revision
- imports
- candidate statement
- proof term / generated theorem
- parents
- operator
- depth
- normalized statement hash
- axioms used
- Lean replay command and result
- novelty classification
- interestingness classification

### PROMOTE

Self-extension is epochal:

```text
Epoch 0: mathlib seeds
Epoch 1: verified candidates from seeds
Epoch 2: verified candidates using seeds + promoted Epoch 1
Epoch 3: consumer probe
```

A retained theorem becomes a new atom only if it passes:

- replay
- dedup
- novelty policy
- promotion policy

Do not promote trivial conjunctions or unused structural packaging lemmas by
default. Promoting junk compounds search explosion.

### MEASURE

Every run emits:

- candidate_count
- lean_checked_count
- lean_accepted_count
- replay_accepted_count
- existing_defeq_duplicate_count
- retained_duplicate_count
- promoted_count
- downstream_used_count
- nontrivial_retained_count
- timeout/error classes

Headline metric:

```text
replay-verified AND not-defeq-to-imported-env AND nontrivial
```

For “human had not written,” be honest:

- Run-level novelty = not definitionally equal to imported environment / bounded
  namespace.
- Global mathlib novelty = later full-index job over all mathlib theorem
  statements.

## 3. Dedup and novelty

Dedup tiers:

```text
syntactic_hash          fast, incomplete
alpha_equivalence       binder-renaming normalization
defeq                  Lean Meta.isDefEq under a canonical telescope
existing_env_defeq      compare against imported mathlib environment
retained_defeq          compare against prior solve records
semantic_equiv          only if solve proves an iff/equality witness
```

Do not claim general semantic equivalence. `isDefEq` is sound but incomplete.
`decide` only applies to closed decidable propositions and is not a general dedup
mechanism.

## 4. Interestingness

Truth is not enough. Most true candidates are mathematically worthless.

Use deterministic value filters before any language model sees the record:

```text
novel AND not closeable by bounded automation AND optionally used downstream
```

Automation oracle candidates:

- `simp`
- `decide`
- `omega`
- `tauto`
- `exact?`

A theorem is likely trivial if bounded library automation closes it immediately
from the seed library. This gives a second verifier-like channel: Lean kernel for
truth, bounded Lean automation for low-value/triviality.

A theorem becomes interesting when it is:

- replay-verified
- not definitionally equal to an imported theorem
- not closed by bounded automation
- used by a downstream verified composition, or shortens a benchmark proof, or
  bridges theorem clusters

Language labels are advisory metadata only.

## 5. Two connectors

### Human Output Connector

```text
retained Atlas/Solve record -> q_lang -> human explanation
```

Explains:

- what was proved
- parent theorems used
- operator composition
- whether it is likely trivial
- whether it was used downstream
- why a candidate failed, translated from Lean error context

It may not mutate retained truth.

### Research Control Connector

```text
human intent -> bounded ExperimentSpec
```

It lets a human steer without writing Lean internals.

Example:

```yaml
version: 1
name: list-basic-depth2-depth3
lean:
  toolchain: leanprover/lean4:v4.31.0
  imports:
    - Mathlib.Data.List.Basic
corpus:
  namespace_prefixes: [List]
  seed_limit: 120
  max_binders: 6
  max_statement_chars: 500
grammar:
  operators:
    - Eq.symm
    - Eq.trans
    - congrArg
    - Iff.intro
    - Iff.mp
    - Iff.mpr
  baseline_operators:
    - And.intro
    - Or.inl
    - Or.inr
bounds:
  max_depth: 2
  promotion_depth: 3
  max_candidates_total: 50000
  max_candidates_per_operator: 5000
  verify_timeout_ms: 1000
dedup:
  existing: defeq_imported_environment
  retained: defeq
promotion:
  require_replay: true
  require_not_existing_defeq: true
  require_downstream_use_within_depth: 3
consumer:
  name: used_by_downstream_verified_composition_within_depth_3
connectors:
  enabled: false
```

The connector can produce this spec, but the spec must validate against a strict
schema before execution. Unknown operators, arbitrary Lean terms, unbounded
imports, and missing budgets are rejected.

## 6. First experiments

The plans disagree usefully:

- Codex recommends `List.Basic` first because it has an automation gap and a
  chance of producing a nontrivial retained theorem.
- Claude recommends `Nat` first because automation will subsume nearly
  everything, making it the cleanest validation of the triviality oracle.

Reconciled sequence:

### Run 0 — Nat control

Purpose: prove the pipeline and triviality filter.

- import: bounded Nat arithmetic module compatible with Lean 4.31/mathlib
- operators: equality fragment + `And.intro` as control
- expected result: many true candidates, almost all killed by automation
- success: receipts, metrics, and measured subsumption rate

### Run 1 — List.Basic discovery attempt

Purpose: give the architecture a real chance to find nontrivial bridge lemmas.

- import: `Mathlib.Data.List.Basic` or discovered current equivalent
- namespace: `List`
- seed count: 50–200
- operators: `Eq.symm`, `Eq.trans`, `congrArg`, `Iff.intro`, `Iff.mp/mpr`
- control operators: `And.intro`, `Or.inl/inr`
- max depth: 2, then promotion probe depth 3
- consumer: `used_by_downstream_verified_composition_within_depth_3`
- success: at least one replay-verified theorem not defeq to imported env,
  nontrivial under bounded automation, and consumed downstream

Honest prediction:

```text
attempted candidates: thousands to tens of thousands
Lean-accepted raw candidates: hundreds to low thousands
after defeq/existing dedup: tens to low hundreds
after nontrivial + downstream-use filters: 0 to 5
genuinely interesting lemmas: likely 0 or 1
```

A successful Run 1 is not “hundreds of new theorems.” A successful Run 1 is a
reproducible verified loop with receipts and one defensible nontrivial retained
theorem, or a quantified proof that the current grammar is being subsumed by
existing automation.

## 7. Repository structure

```text
pyproject.toml
README.md
ARCHITECTURE.md
lean-toolchain
lakefile.lean
lake-manifest.json

src/solve/
  cli.py
  experiments/spec.py
  corpus/mathlib.py
  lean/protocol.py
  lean/worker.py
  grammar/operators.py
  grammar/enumerator.py
  verify/dedup.py
  verify/receipts.py
  retain/store.py
  retain/promote.py
  measure/metrics.py
  connectors/human_output.py
  connectors/research_control.py
  connectors/providers.py
  review/dual_lane.py

lean/Solve/
  Verifier.lean
  Protocol.lean
  Corpus/Enumerate.lean
  Kernel/Check.lean
  Kernel/Dedup.lean
  Generated/Epoch0.lean

tests/
  test_spec.py
  test_operator_registry.py
  test_dedup_policy.py
  test_receipts.py
  test_hardline.py
  lean_fixtures/

experiments/
  run0_nat_control.yaml
  run1_list_basic_depth2.yaml

reproduce/
  run0.sh
  run1.sh
```

## 8. Reproduce gates

```bash
pip install -e ".[dev]"
solve doctor
lake exe cache get
pytest
pytest -m lean
solve run experiments/run0_nat_control.yaml
solve replay runs/<id>/receipts.jsonl
lake env lean lean/Solve/Generated/EpochN.lean
```

CI should gate deterministic artifacts only. LLM connector text is not part of
reproduction gates.

## 9. Build order

1. `ExperimentSpec` schema and validation
2. Lean smoke check (`solve doctor`, toolchain, Lake project)
3. Minimal Lean replay of one generated theorem
4. Operator registry + unit tests
5. Candidate receipt schema + JSONL replay
6. Dedup policy scaffolding
7. Run 0 Nat control
8. Research Control Connector
9. Human Output Connector
10. Run 1 List.Basic discovery attempt

## 10. Review gates

Dual-lane review is required for:

- Lean worker
- operator registry
- dedup
- retention/promote
- connector boundary
- Run 0/Run 1 claim language

Lane A reviews correctness and tests. Lane B reviews the trust boundary:

- no LLM truth
- no retention without replay
- no silent global-memory/Atlas writes
- no unbounded generation
- no claim promotion beyond receipts
