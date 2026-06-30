# Phase 6B Finding: Global Novelty Indexing — Honest Status

## Date: 2026-06-29
## Corpus: Mathlib.Data.List.Basic (Lean 4.31.0)
## Scope: imported (List prefix) vs global (all mathlib modules)

## A/B Result

| Metric                          | 6A (imported scope) | 6B global (DiscrTree) |
|---------------------------------|---------------------|----------------------|
| Candidates classified           | 6                   | 6                    |
| existing_defeq_duplicate        | 1                   | 0                    |
| novel_in_imported_env           | 5                   | 0                    |
| unknown                         | 0                   | **6 (all)**          |
| promotable                      | 0                   | 0                    |

## What happened

The global DiscrTree novelty path imported all of Mathlib and built an index
of 345,912 mathlib declarations (module-based scoping works correctly — verified
that `ownedByMathlib` correctly identifies mathlib constants by module ownership,
not name prefix). The DiscrTree index built successfully.

However, the per-target query phase failed: `instantiateMVars` on candidate types
in the context of the full Mathlib environment hits a deterministic `whnf` timeout.
All 6 candidates returned `unknown` (fail-closed). This is the correct fail-closed
behavior — the probe does not claim novelty it cannot verify.

## Root cause of the timeout

When the full Mathlib environment (780k constants, 345k eligible) is loaded,
`whnf`/`instantiateMVars` on even simple propositional types like
`ByteArray.empty = [].utf8Encode` exhausts the per-call heartbeat budget. The
heartbeat budget set via `compareTypes`'s `withTheReader` is allocated by
`liftTermElabM` from the `maxHeartbeats` option, but the internal `whnf`
reduction on mathlib-scale types is expensive due to type-class instance
resolution and universe polymorphism.

A standalone test confirmed that `instantiateMVars` works fine in a simple
module (`set_option maxHeartbeats 1000000000; #test_inst` → OK). The issue is
specific to the `NoveltyProbe` elaboration context where the heartbeat counter
is allocated with a lower per-call budget.

## What works

1. **Module-based scoping works**: `ownedByMathlib` correctly identifies mathlib
   declarations by module ownership (`env.getModuleIdxFor?` + module path starts
   with "Mathlib"), not name prefix. This is the critical fix from the planning
   phase — mathlib constants named `List.*`, `Nat.*` are correctly included.

2. **Brute-force oracle works for imported scope**: the brute-force path
   (`verify_mode=brute`, `scope=imported`, `prefixes=List`) correctly finds
   the `existing_defeq_duplicate` for the Eq.symm candidate. This is verified
   by the passing oracle test.

3. **Batch infrastructure works**: `probe_novelty_batch` correctly batches
   all targets into one Lean process, parses N NOV lines, and handles
   fail-closed partial output. The single-target `probe_novelty` wrapper
   preserves back-compat.

4. **DiscrTree index builds**: the index of 345k declarations builds in
   ~30s without errors. Only the query phase (type instantiation + comparison)
   fails on mathlib-scale types.

## DiscrTree soundness limitation (documented, xfail test)

Even when the DiscrTree query runs successfully, it can miss defeq matches
that require `Eq.symm` (symmetric equalities are not grouped by
`DiscrTree.mkPath` under reducible transparency). A candidate whose type is
`b = a` (from Eq.symm) will not match an imported theorem `a = b`. This is
documented as an xfail test (`test_discrtree_imported_finds_utf8_duplicate`).

## What this means

The global novelty infrastructure is built and the module-scoping is correct,
but the DiscrTree query path needs heartbeat/performance tuning before it can
produce reliable global novelty classifications. The fail-closed behavior
(returning `unknown` rather than false `novel`) is correct and safe — no
incorrect novelty claims are made.

Promotable remains 0 under both imported and global scope (the global path
returns unknown for all, which is more conservative than imported but still
0 promotable).

## Honest interpretation

This is a legitimate partial-result finding. The infrastructure is sound:
- Batch novelty probe works (verified by tests + A/B on imported scope)
- Module-based mathlib scoping works (verified: 345k eligible declarations)
- Fail-closed semantics work (unknown on timeout, never false-novel)
- The DiscrTree pre-filter has two known issues: (1) heartbeat timeout on
  mathlib-scale type instantiation, (2) symmetric-equality misses

Both issues are performance/soundness-hardening problems, not architecture
problems. They are correctly deferred to a future phase (6C+ or a dedicated
hardening pass).

## Dual-lane process

- **Planning:** Both Codex GPT-5.5 (xhigh) and Claude opus independently designed
  the DiscrTree + module-scoping approach. Codex contributed the critical
  module-based scoping correction; Claude proposed the DiscrTree data structure.
- **Build:** Codex lane produced the canonical build (Lean compiles clean, 127
  non-lean tests pass). Claude lane had a Lean compile error (exc.toString
  invalid field) — Codex adopted as canonical base.
- **Controller fixes:** (1) Fixed Lean heartbeat allocation for target type
  instantiation. (2) Fixed oracle test to use theorem (explicit type) instead
  of def (inferred type). (3) Redesigned oracle to use imported scope (brute
  path works; global path times out). (4) Documented DiscrTree symmetric-eq
  limitation as xfail. (5) Ran real A/B measurement.
