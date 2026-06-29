from __future__ import annotations

from solve.grammar.iff_mpr import generate_iff_mpr_candidates
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


def test_generator_emits_ordered_iff_candidates():
    candidates = generate_iff_mpr_candidates(
        [atom("B.iff", "Q ↔ R"), atom("A.iff", "P ↔ Q"), atom("C.bad", "P → Q")],
        max_candidates=10,
        experiment_name="x",
    )
    assert [candidate.parents for candidate in candidates] == [("A.iff",), ("B.iff",)]
    assert [candidate.statement for candidate in candidates] == ["Q → P", "R → Q"]
    assert all(candidate.operator == "Iff.mpr" for candidate in candidates)


def test_generator_filters_non_theorems_and_wrong_shapes():
    candidates = generate_iff_mpr_candidates(
        [atom("A.def", "P ↔ Q", "def"), atom("B.bad", "P → Q"), atom("C.iff", "R ↔ S")],
        max_candidates=10,
        experiment_name="x",
    )
    assert [candidate.parents for candidate in candidates] == [("C.iff",)]
    assert candidates[0].parent_atom_kinds == ("theorem",)


def test_rejects_atom_with_binders():
    candidates = generate_iff_mpr_candidates(
        [atom("A.iff", "∀ x, P x ↔ Q x", binder_count=1)],
        max_candidates=10,
        experiment_name="x",
    )
    assert candidates == []


def test_generator_zero_cap_yields_empty_list():
    assert generate_iff_mpr_candidates([atom("A.iff", "P ↔ Q")], max_candidates=0, experiment_name="x") == []


def test_generator_is_deterministic_and_ids_are_stable():
    atoms = [atom("B.iff", "Q ↔ R"), atom("A.iff", "P ↔ Q")]
    first = generate_iff_mpr_candidates(atoms, max_candidates=10, experiment_name="x")
    second = generate_iff_mpr_candidates(atoms, max_candidates=10, experiment_name="x")
    assert first == second
    assert [candidate.candidate_id for candidate in first] == [candidate.candidate_id for candidate in second]


def test_distinct_parent_tuples_have_distinct_ids():
    candidates = generate_iff_mpr_candidates(
        [atom("A.iff", "P ↔ Q"), atom("B.iff", "Q ↔ R")],
        max_candidates=10,
        experiment_name="x",
    )
    assert candidates[0].candidate_id != candidates[1].candidate_id
