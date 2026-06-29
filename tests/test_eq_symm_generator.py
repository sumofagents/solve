from solve.grammar.eq_symm import generate_eq_symm_candidates
from solve.lean.atoms import AtomRecord


def atom(name: str, type_pp: str, kind: str = "theorem") -> AtomRecord:
    return AtomRecord(
        name=name,
        kind=kind,
        type_pp=type_pp,
        type_hash=f"hash-{name}",
        binder_count=0,
        arity=0,
        module="Test",
        axioms=[],
    )


def test_generator_emits_ordered_equality_candidates():
    candidates = generate_eq_symm_candidates(
        [atom("B.eq", "b = c"), atom("A.eq", "a = b"), atom("C.bad", "True")],
        max_candidates=10,
        experiment_name="x",
    )
    assert [candidate.parents for candidate in candidates] == [("A.eq",), ("B.eq",)]
    assert [candidate.statement for candidate in candidates] == ["b = a", "c = b"]
    assert all(candidate.operator == "Eq.symm" for candidate in candidates)
    assert all(candidate.proof_term for candidate in candidates)


def test_generator_filters_non_theorems_and_wrong_shapes():
    candidates = generate_eq_symm_candidates(
        [atom("A.def", "a = b", "def"), atom("B.bad", "P ↔ Q"), atom("C.eq", "c = d")],
        max_candidates=10,
        experiment_name="x",
    )
    assert [candidate.parents for candidate in candidates] == [("C.eq",)]
    assert candidates[0].parent_atom_kinds == ("theorem",)


def test_generator_zero_cap_yields_empty_list():
    assert generate_eq_symm_candidates([atom("A.eq", "a = b")], max_candidates=0, experiment_name="x") == []


def test_generator_is_deterministic_and_ids_are_stable():
    atoms = [atom("B.eq", "b = c"), atom("A.eq", "a = b")]
    first = generate_eq_symm_candidates(atoms, max_candidates=10, experiment_name="x")
    second = generate_eq_symm_candidates(atoms, max_candidates=10, experiment_name="x")
    assert first == second
    assert [candidate.candidate_id for candidate in first] == [candidate.candidate_id for candidate in second]


def test_distinct_parent_tuples_have_distinct_ids():
    candidates = generate_eq_symm_candidates(
        [atom("A.eq", "a = b"), atom("B.eq", "b = c")],
        max_candidates=10,
        experiment_name="x",
    )
    assert candidates[0].candidate_id != candidates[1].candidate_id
