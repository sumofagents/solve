# Phase 5c Finding: Run1 List.Basic Structural-Only Execution

## Date: 2026-06-29
## Corpus: Mathlib.Data.List.Basic (Lean 4.31.0)
## Grammar: And.intro structural-only (baseline operator)
## Candidates: 50 (capped)

## Results

| Filter Stage             | Count | Notes                                    |
|--------------------------|-------|------------------------------------------|
| Total candidates         | 50    | And.intro pairs of List.* theorem atoms   |
| Replay-accepted (truth)  | 50    | All 50 compile under lake env lean        |
| Novel (not defeq dup)    | 50    | No defeq duplicates in imported env       |
| Structural packaging     | 50    | All are And.intro of imported atoms       |
| Ingredient-trivial       | 25    | simp [ParentA, ParentB] closes them       |
| Ingredient-unknown       | 25    | simp [parents] probe returned unknown     |
| **Promotable**           | **0** | All killed by trivial OR probe uncertainty|
| Interesting (downstream) | 0     | No promotable → no promoted atoms → no epoch-1 |

## Interpretation

This is the predicted clean negative finding from the dual-lane planning consensus:

- **Claude predicted ~3% probability** of ≥1 interesting theorem.
- **Codex predicted ~2% probability**.
- **Actual: 0%.**

The structural-only grammar (And.intro) produces candidates that are all:
1. Replay-verified (kernel accepts the composition).
2. Novel (not defeq-duplicate of any existing theorem).
3. BUT trivial under the value layer — all 50 are structural packaging
   (And.intro of imported atoms), and half are also ingredient-trivial
   (closeable by bounded automation given parent hints).

No candidate earns promotion. Without promoted atoms, the self-extension
mechanism (5a) has nothing to promote, downstream_used detection (5b)
has no epoch-1 consumers to probe, and the interesting label cannot fire.

## What this proves

1. The triviality filter works correctly on a second corpus (List.Basic),
   confirming the Run0 result: structural packaging is subsumed by the
   value layer.

2. The self-extension mechanism (5a) and downstream_used detection (5b)
   are verified on synthetic fixtures in their respective test suites.

3. Grammar widening is empirically justified: structural-only grammar
   cannot clear the triviality gate on either Nat (Run0) or List.Basic
   (Run1) corpora.

## Next phase

Phase 5d (or Phase 6a): widen the grammar to typed operators (Eq.symm,
Eq.trans, congrArg, Iff.*) that can synthesize new statements rather
than package existing ones. Re-run on List.Basic as an A/B against this
baseline. Reuse 5a/5b infrastructure unchanged.

## Honest framing

This is single-epoch structural-only measurement, not full self-extension
under fair enumeration (the paper's theorem). The mechanism is verified
on synthetic fixtures; the real-corpus negative is the empirical bridge
from "filter works" to "grammar must widen."
