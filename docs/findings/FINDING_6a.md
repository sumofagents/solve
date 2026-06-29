# Phase 6A Finding: Binder-Aware Type-Directed Atom Selection on List.Basic

## Date: 2026-06-29
## Corpus: Mathlib.Data.List.Basic (Lean 4.31.0)
## Grammar: Eq.symm, Eq.trans, congrArg, Iff.intro, Iff.mp, Iff.mpr + And.intro baseline
## Filter: binder_count == 0 on all typed-operator parents; congrArg head-name guard

## A/B vs Phase 5d

| Metric                          | 5d (no binder filter) | 6A (binder-filtered) |
|---------------------------------|----------------------|---------------------|
| Total candidates                | 25                   | 6                   |
| Replay-attempted                | 25                   | 6                   |
| Replay-accepted                 | 5                    | 6                   |
| Typed-operator accept rate      | 0/20 (0%)            | **1/1 (100%)**      |
| Retained                        | 5                    | 6                   |
| Novel                           | 5/5                  | 5/6                 |
| Structural packaging            | 5                    | 5 (+1 unknown)      |
| Ingredient-trivial              | 1                    | 2 (+4 unknown)      |
| **Promotable**                  | **0**                | **0**               |

## Per-operator breakdown (6A)

| Operator   | Bare parents | Candidates | Replay-accepted |
|------------|--------------|------------|-----------------|
| Eq.symm    | 1 (List.utf8Encode_nil) | 1 | **1 (100%)** |
| Eq.trans   | 1 (no matching middle)  | 0 | 0             |
| congrArg   | 1 eq x 0 head-matching fns | 0 | 0          |
| Iff.mp     | 0                       | 0 | 0             |
| Iff.mpr    | 0                       | 0 | 0             |
| Iff.intro  | 0 bare implications     | 0 | 0             |
| And.intro  | baseline                | 5 | 5             |

## Headline

Type-directed binder-aware selection raised the typed-operator replay-accept
rate from **0% (0/20) to 100% (1/1)**. Every typed-operator candidate that is
now generated actually type-checks in the Lean kernel. The binder filter
eliminated the entire class of ill-typed emissions that caused Phase 5d's
20/20 replay failure.

## The single typed candidate

The lone typed candidate is `Eq.symm @List.utf8Encode_nil`, producing:

    ByteArray.empty = [].utf8Encode

This is well-typed and replay-accepted. However it is classified as an
**existing_defeq_duplicate** — it is definitionally equal to the already-imported
theorem `List.utf8Encode_nil` (whose statement is `[].utf8Encode = ByteArray.empty`,
the symmetric form). The novelty filter correctly rejects it.

## Why promotable is still 0

Two independent reasons, both correct:

1. **The Eq.symm candidate is not novel.** It is the symmetry of an imported
   theorem, which is defeq to the original. The novelty gate correctly classifies
   it as `existing_defeq_duplicate`.

2. **The And.intro candidates are structural-packaging.** They package two
   existing theorems into a conjunction without producing new mathematical
   content. The triviality filter correctly classifies them.

## Root cause confirmed (binder/instantiation mismatch)

Phase 5d's 20/20 typed-operator replay failure was caused by a
binder/instantiation mismatch, confirmed by both independent planning lanes
(Codex GPT-5.5 xhigh + Claude opus) and independently verified by the controller:

- The typed generators filtered parent atoms by TEXTUAL shape
  (parse_equality/parse_iff) but ignored AtomRecord.binder_count.
- A theorem `thm : forall {a}, forall x, lhs = rhs` has binder_count >= 2.
  The proof term `Eq.symm @thm` is ill-typed because `@thm` has type
  `forall ..., lhs = rhs`, not the bare `a = b` that Eq.symm requires.
- The textual parser strips ONE forall block and sees the `=` in the body,
  so it accepted the atom — but the bare proof term could not elaborate.

## Corpus evidence (independently verified against .hermes/atoms_run1.json)

- 120 atoms total, 103 theorems.
- binder_count distribution: {3: 32, 4: 20, 5: 20, 6: 13, 2: 7, 7: 3, 8: 3, 10: 2, 1: 1, 9: 1, 0: 1}
- Only 1 theorem has binder_count == 0: `List.utf8Encode_nil`.
- Zero-binder atoms that parse as iff: 0. As implication: 0.
- The in-tree test `test_phase6a_binder_filter_corpus_evidence.py` locks this
  projection: eq_symm <= 1, all other typed operators == 0.

## What this proves

1. **The binder filter works.** Typed-operator replay-accept went from 0/20 to 1/1.
   Every generated typed candidate is now well-typed by construction.

2. **The replay gate remains honest.** The one candidate that survives is
   genuinely accepted by the Lean kernel, not mocked.

3. **The triviality/novelty gates remain honest.** The Eq.symm candidate is
   correctly rejected as existing_defeq_duplicate; the And.intro candidates
   are correctly rejected as structural-packaging.

4. **The bottleneck is now corpus topology, not Python-side filtering.**
   Only 1 of 103 theorems in List.Basic is a bare proposition. Type-directed
   selection cannot produce more candidates than the corpus affords.

## What this means for the project

The structural correctness of the typed grammar is now established: the
generators emit only well-typed proof terms, and replay confirms them. The
mechanism is sound. The limiting factor is the rarity of bare propositions
in mathlib (101 of 103 List.Basic theorems have >= 2 binders), which means
bare-operator application can reach almost nothing.

The next first-order improvement is **binder instantiation** (Phase 6B):
an operator family that re-introduces the universals as a proof lambda and
applies the bare operator to the instantiated body. This requires a structured
binder dump from Solve.Tools.AtomDump (currently only binder_count is emitted).

## Dual-lane process

- **Planning:** Both Codex GPT-5.5 (xhigh) and Claude opus independently
  confirmed the binder root cause with corpus evidence and converged on the
  same design. No contested decisions.
- **Build:** Codex lane produced verified-green implementation (149 passed,
  1 skipped, 0 failed full suite). Claude lane produced functionally equivalent
  source modules but its test files used `int | None` annotations
  (Python 3.10+ only), breaking collection on Python 3.9.6. Codex adopted
  as canonical base.
- **Review:** [pending dual-lane review of this commit]
