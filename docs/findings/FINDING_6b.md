# Phase 6B Finding: Global Novelty Indexing — Fixed Instrument

## Date: 2026-06-29 / hardened 2026-06-30
## Corpus: Mathlib.Data.List.Basic (Lean 4.31.0)
## Scope: imported List prefix vs global library modules (`Init`, `Std`, `Lean`, `Mathlib`)

## A/B Result after hardening

| Metric                          | 6A imported scope | 6B global brute scope |
|---------------------------------|-------------------|-----------------------|
| Candidates classified           | 6                 | 6                     |
| existing_defeq_duplicate        | 1                 | 1                     |
| novel_in_imported_env           | 5                 | 5                     |
| unknown                         | 0                 | 0                     |
| promotable                      | 0                 | 0                     |

The global novelty instrument now runs to completion. It does **not** change the
promotable count on `List.Basic`: all retained candidates still fail the value
bar because the surviving And.intro candidates are structural packaging, and the
Eq.symm candidate is an existing duplicate.

## What was fixed

The first 6B implementation was safely fail-closed but operationally unusable:
global novelty returned `unknown` for all 6 candidates. The causes were real and
separate:

1. **Per-comparison timeout:** `compareTypes?` called `instantiateMVars` on stored
   declaration types. Stored theorem declarations are closed Exprs; forcing
   `instantiateMVars` on them in the full library environment triggered expensive
   `whnf` work and exhausted the heartbeat budget. Fix: skip `instantiateMVars`
   only when `Expr.hasMVar = false`; if metavariables are present, run
   `instantiateMVars` and fail-closed on exception.

2. **Heartbeat too low for global brute:** the CLI/value defaults passed
   `20_000` heartbeats, which Lean reports as ~20 per comparison in the relevant
   error path. Fix: global-safe novelty default is now `2_000_000`.

3. **Global timeout too low:** 300s could kill the full 6-target brute run.
   Fix: global novelty timeout default is now 900s.

4. **Candidate cap too low for global brute:** 5,000 was below the global library
   eligible set, so every target cap-hit and returned `unknown`. Fix: default
   novelty candidate cap is now 500,000.

5. **Scope too narrow:** the original "global" scan only included declarations
   owned by `Mathlib.*` modules. The duplicate witness for the Eq.symm candidate
   can live in core modules such as `Init.Data.ByteArray.Lemmas`. Fix: global
   scope now includes modules owned by `Init`, `Std`, `Lean`, and `Mathlib`, while
   still excluding generated `Solve.*` modules.

## Evidence

Known duplicate oracle:

- Target: `Solve.Generated.RunControl.novelty_global_utf8_dup`
- Type: `ByteArray.empty = [].utf8Encode`
- Global brute result: `existing_defeq_duplicate`
- Witness observed: `ByteArray.emptyWithCapacity_eq_empty`
- Compared: 52,187 candidates before first witness
- cap_hit: false

Run1 List.Basic global A/B:

- Classified: 6 retained receipts
- Novelty: 1 existing duplicate, 5 novel, 0 unknown
- Promotable: 0/6

## What this proves

1. Global novelty is now a working instrument, not just a fail-closed shell.
2. Global scope must include Lean core library modules (`Init`, `Std`, `Lean`) in
   addition to `Mathlib`; module-name prefix `Mathlib.*` alone is not global.
3. Brute mode is the sound default. DiscrTree remains an opt-in performance path.
4. The timeout fix improves measurement only; it does not create a positive case.
   The List.Basic value bottleneck remains corpus/grammar quality, not novelty.

## DiscrTree soundness limitation (documented, xfail test)

DiscrTree narrowing can miss defeq matches that require `Eq.symm`; symmetric
equalities are not grouped by `DiscrTree.mkPath` under reducible transparency.
This is documented as an xfail test (`test_discrtree_imported_finds_utf8_duplicate`).
Until the query includes symmetric variants or another completeness argument,
`discrtree` is opt-in only; `brute` is the sound default.

## Dual-lane process

- **Planning:** Codex GPT-5.5 and Claude opus independently designed global
  novelty indexing. Claude proposed DiscrTree; Codex caught the module-scoping
  issue (names like `List.*` are not `Mathlib.*`).
- **Build:** Codex build adopted as canonical because its Lean code compiled;
  Claude build had a Lean compile error.
- **Review:** Codex REQUEST_CHANGES, Claude APPROVE-with-nits. Codex found real
  fail-closed issues; controller fixed them: tri-state comparisons, brute
  default, build failure handling, higher heartbeat/timeout/cap, conditional
  mvar instantiation, and broader global library module scope.

## Honest interpretation

Phase 6B now answers the intended question on this corpus: comparing against the
broader library does not surface new value. It confirms the same basic result as
6A with stronger novelty evidence: 5 candidates are globally novel but structural;
1 candidate is globally duplicate; 0 are promotable.
