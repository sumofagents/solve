from __future__ import annotations

from solve.grammar.iff_intro import generate_iff_intro_candidates
from solve.lean.atoms import AtomRecord


def atom(name: str, type_pp: str, kind: str = "theorem", binder_count: int | None = 0) -> AtomRecord:
    return AtomRecord(
        name=name,
        kind=kind,
        type_pp=type_pp,
        type_hash=f"hash-{name}",
        binder_count=binder_count,
        arity=0,
        module="Test",
        axioms=[],
    )


def test_generator_emits_ordered_mirrored_implication_pairs():
    candidates = generate_iff_intro_candidates(
        [atom("B.reverse", "Q → P"), atom("A.forward", "P → Q"), atom("C.bad", "P ↔ Q")],
        max_candidates=10,
        experiment_name="x",
    )
    assert [candidate.parents for candidate in candidates] == [
        ("A.forward", "B.reverse"),
        ("B.reverse", "A.forward"),
    ]
    assert [candidate.statement for candidate in candidates] == ["P ↔ Q", "Q ↔ P"]
    assert all(candidate.operator == "Iff.intro" for candidate in candidates)


def test_generator_filters_non_theorems_wrong_shapes_and_nonmirrors():
    candidates = generate_iff_intro_candidates(
        [atom("A.forward", "P → Q"), atom("B.nope", "R → P"), atom("C.def", "Q → P", "def")],
        max_candidates=10,
        experiment_name="x",
    )
    assert candidates == []


def test_rejects_atom_with_binders():
    candidates = generate_iff_intro_candidates(
        [
            atom("A.forward", "∀ x, P x → Q x", binder_count=1),
            atom("B.reverse", "∀ x, Q x → P x", binder_count=1),
        ],
        max_candidates=10,
        experiment_name="x",
    )
    assert candidates == []


def test_generator_zero_cap_yields_empty_list():
    assert generate_iff_intro_candidates([atom("A.forward", "P → Q")], max_candidates=0, experiment_name="x") == []


def test_generator_is_deterministic_and_ids_are_stable():
    atoms = [atom("B.reverse", "Q → P"), atom("A.forward", "P → Q")]
    first = generate_iff_intro_candidates(atoms, max_candidates=10, experiment_name="x")
    second = generate_iff_intro_candidates(atoms, max_candidates=10, experiment_name="x")
    assert first == second
    assert [candidate.candidate_id for candidate in first] == [candidate.candidate_id for candidate in second]


def test_distinct_parent_tuples_have_distinct_ids():
    candidates = generate_iff_intro_candidates(
        [atom("A.forward", "P → Q"), atom("B.reverse", "Q → P")],
        max_candidates=10,
        experiment_name="x",
    )
    assert candidates[0].candidate_id != candidates[1].candidate_id
