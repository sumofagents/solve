# Phase 6C Finding: Proof-Shortening Measurement Mechanism

## Date: 2026-06-29
## Corpus: synthetic fixture (mechanism); Mathlib.Data.List.Basic (real evidence: DEFERRED)
## Toolchain: Lean 4.31.0

## Headline

- **Mechanism: PASS on a synthetic fixture.** A new Lean probe measures the
  elaborated proof Expr node count of a declaration's value, and a Python
  orchestrator compares baseline ("without") vs with-promoted proofs of the
  same proposition.
- **Real List.Basic evidence: DEFERRED.** Phases 6A and 6B left
  `List.Basic` with **0 promotable candidates**, so there are 0 with-promoted
  proofs to measure. No proof-shortening value claim is made for
  `List.Basic`.

## What was built

### Lean probe (`lean/Solve/Tools/ProofSizeProbe.lean`)

- Options:
  - `solve.proofsize.target` (fully-qualified theorem/def/opaque name).
  - `solve.proofsize.requiredConst` (optional fully-qualified constant
    expected to appear inside the proof body; empty string = no usage check).
- Behavior:
  1. Look up the target in the environment.
  2. Extract the value: `thmInfo.value`, `defnInfo.value`, or
     `opaqueInfo.value`. Other constant kinds emit `verdict="unknown"`.
  3. Recursively count `Expr` nodes after stripping `.mdata` metadata wrappers.
     Counts apps, lambdas, foralls, lets, projections, constants, fvars, mvars,
     sorts, lits, and bvars. Metadata wrappers are not counted; the metric is
     over the metadata-stripped proof/value expression.
  4. If `requiredConst` is non-empty, recurse over the value and check whether
     that name appears as a `.const` anywhere.
- Output: exactly one `PROOFSIZE {...}` JSON line plus `PROOFSIZE_DONE`.
  Payload fields: `target`, `verdict` (`"ok"` / `"unknown"`), `term_size`
  (int or null), `required_const` (string or null), `used_required_const`
  (bool or null), `reason`.
- **Fail-closed:** missing target, unsupported kind, parse failure, and any
  exception during instantiation/measurement yield `verdict="unknown"` with
  `term_size=null` and a `reason` describing the cause. `lake env lean`
  non-zero exit / timeout / unparseable stdout all map to `unknown` in the
  Python wrapper.

### Python wrapper (`src/solve/lean/proof_size.py`)

- `ProofSizeResult` dataclass mirrors the JSON payload.
- `parse_proof_size_output(stdout)` enforces exactly one `PROOFSIZE` line and
  a `PROOFSIZE_DONE` marker, validates types (including rejecting `bool`
  passed where `int` is expected for `term_size`).
- `probe_proof_size(target, *, repo, imports, required_const, timeout, ...)`
  writes a transient wrapper under `lean/Solve/Generated/ProofSizeProbe_<safe>.lean`,
  runs `lake env lean` with `-Dweak.solve.proofsize.target=...` and
  `-Dweak.solve.proofsize.requiredConst=...`, and always unlinks the
  generated wrapper in a `finally`. Pre-build via `build_modules` is called
  first; build failure -> `unknown`.

### Shortening orchestrator (`src/solve/measure_shortening.py`)

- `BenchmarkRow`: `benchmark_id`, `imports`, `without_target`,
  `with_target`, optional `promoted_const`.
- `measure_shortening([...], repo=..., ...)` runs the probe twice per row.
- `ShorteningRow` includes `without_size`, `with_size`, `delta_absolute`,
  `delta_ratio`, `used_promoted_in_with`, `verdict`, `reason`.
- **Verdict rules:**
  - Either probe returned `unknown` → row `unknown`.
  - `promoted_const` set and `used_required_const` is not `True` → row
    `unknown` (do not claim shortening if the promoted theorem was not
    actually used).
  - `with_size < without_size` → `shorter`.
  - Otherwise → `not_shorter`.
- `summarize(rows)` returns `ShorteningMetrics(total, counts_by_verdict,
  shortened_count, unknown_count)`.

### CLI (`solve measure-shortening`)

```
solve measure-shortening <spec> \
  --benchmarks path.jsonl \
  --out out.jsonl \
  --metrics metrics.json \
  [--repo .] [--timeout 60] [--heartbeat-budget 20000] [--rec-depth 1000]
```

The spec argument is accepted for parity with sibling commands; benchmark
rows carry their own `imports`.

### Synthetic fixture

`lean/Solve/Generated/ProofShorteningSynthetic.lean` (gitignored;
materialized by tests) defines:

- `promoted_pair : True ∧ True := And.intro True.intro True.intro`
- `without_pair`: a baseline using nested `let`-bindings to force the
  elaborated Expr to be strictly larger.
- `with_pair : True ∧ True := promoted_pair`

Probe results in CI:

- `without_pair.term_size` >> `with_pair.term_size`
- `with_pair` uses `promoted_pair` (required-const check returns `true`).
- Orchestrator verdict: `shorter`, `used_promoted_in_with = true`,
  `delta_absolute > 0`, `delta_ratio > 0`.

## Why real List.Basic evidence is deferred, not measured

Phase 6A and Phase 6B both converged on:

- 6 retained classified candidates on `Mathlib.Data.List.Basic`.
- 0 promotable: 5 are structural-packaging And.intros; 1 is an existing
  `Eq.symm` duplicate (confirmed globally novel-or-duplicate, but still not
  value-bearing).

A proof-shortening benchmark requires a with-promoted proof of some
proposition that actually uses a promoted theorem. With **0** promoted
theorems for `List.Basic`, there is no with-target to construct. Running
the orchestrator on a synthesized non-promoted with-target would not be a
List.Basic value claim — it would be a re-test of the synthetic mechanism.

We therefore explicitly DEFER real List.Basic proof-shortening evidence to
the future phase that produces a non-zero promotable count.

## What this proves and does not prove

**Proves:**
- The proof-shortening instrument (Lean Expr counter + orchestrator + CLI)
  works end-to-end and produces a real `shorter` verdict on a real Lean
  fixture.
- Fail-closed semantics are preserved: missing targets, unsupported
  constant kinds, build/parse/timeout failures all map to `unknown` with
  `term_size=null`.
- The `used_required_const` check prevents false-positive shortening
  claims when a with-target proof is incidentally shorter without actually
  using the promoted theorem.

**Does NOT prove:**
- That `List.Basic` admits any promoted theorem that shortens a proof —
  there are 0 promotable candidates today (6A/6B finding stands).
- That any specific promoted constant is "useful" in Mathlib; that question
  is downstream of producing a non-zero promotable count.

## Status table

| Question                                           | Status      |
|----------------------------------------------------|-------------|
| Mechanism works (synthetic)                        | PASS        |
| Fail-closed on probe failure                       | PRESERVED   |
| Real `List.Basic` proof-shortening evidence        | DEFERRED    |
| `List.Basic` promotable count                      | 0 (unchanged) |
| Existing value/promotion gate                      | unchanged   |
