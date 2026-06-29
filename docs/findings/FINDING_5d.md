# Phase 5d Finding: Typed Grammar A/B vs 5c on List.Basic

## Date: 2026-06-29
## Corpus: Mathlib.Data.List.Basic (Lean 4.31.0)
## Grammar: Eq.symm, Eq.trans, congrArg, Iff.intro, Iff.mp, Iff.mpr + And.intro baseline
## Candidates: 25 (round-robin interleaved across 5 operators that produced output)

## A/B Comparison

| Metric                   | 5c (structural-only) | 5d (typed grammar) |
|--------------------------|----------------------|--------------------|
| Total candidates         | 50                   | 25                 |
| Replay-accepted          | 50                   | 5                  |
| Retained operator mix    | And.intro: 50        | And.intro: 5       |
| Novel                    | 50/50                | 5/5               |
| Structural packaging     | 50/50                | 5/5               |
| Ingredient-trivial       | 25/50                | 1/5               |
| **Promotable**           | **0/50**             | **0/5**           |

## Key finding

Typed grammar operators (Eq.symm, Eq.trans, congrArg, Iff.mp, Iff.mpr)
were implemented and generated 20 candidates (5 per operator). ALL 20
failed replay — the proof terms did not type-check because the generators
apply typed operators to atoms whose types don't match the operator's
requirements.

Only And.intro candidates survived replay (5/5), because And.intro accepts
any pair of propositions. Those 5 are all structural-packaging → not
promotable.

## Interpretation

Grammar widening alone is NOT sufficient to produce promotable candidates.
The bottleneck is not grammar breadth but type-directed atom selection:
- Eq.symm requires its argument to be an equality (`a = b`). Most List.*
  theorems are universal quantifications, not equalities.
- Iff.mp/mpr require their argument to be an iff (`p ↔ q`). Few List.*
  theorems are iffs.
- congrArg requires a function and an equality. The pairing must match.

The type_shape module was created to filter atoms by type shape, but the
generators do not use it strongly enough — they try all atoms with all
operators, and the replay gate correctly rejects the mismatches.

## What this proves

1. The typed grammar dispatch works: round-robin interleaving ensures
   typed operators are not starved by And.intro.

2. The replay gate correctly rejects type-mismatched candidates (20/20
   typed-operator candidates failed, 5/5 And.intro succeeded).

3. The triviality filter correctly classifies all surviving candidates
   as structural-packaging (the only survivors are And.intro pairs).

4. Phase 6 needs type-directed atom selection, not just grammar widening:
   filter atoms by the operator's required type shape BEFORE generating
   candidates. This will reduce the replay-failure rate and give typed
   operators a real chance to produce non-structural, non-trivial results.

## Honest framing

This A/B confirms the planning prediction: grammar widening from
structural-only to typed operators does NOT clear the terminal bar
(novel + non-trivial + downstream-used) on List.Basic in a single phase.
Both lanes predicted ~10-20% probability; actual is 0%. The limiting
factor is type-directed generation quality, not grammar breadth.
