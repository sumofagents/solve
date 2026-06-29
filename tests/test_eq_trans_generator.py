from solve.grammar.eq_trans import generate_eq_trans_candidates
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


def test_generator_emits_ordered_matching_trans_candidates():
    candidates = generate_eq_trans_candidates(
        [atom("B.bc", "b = c"), atom("A.ab", "a = b"), atom("C.cd", "c = d")],
        max_candidates=10,
        experiment_name="x",
    )
    assert [candidate.parents for candidate in candidates] == [("A.ab", "B.bc"), ("B.bc", "C.cd")]
    assert [candidate.statement for candidate in candidates] == ["a = c", "b = d"]
    assert all(candidate.operator == "Eq.trans" for candidate in candidates)


def test_generator_filters_non_theorems_wrong_shapes_and_nonmatching_middle():
    candidates = generate_eq_trans_candidates(
        [
            atom("A.ab", "a = b"),
            atom("B.bad", "P ↔ Q"),
            atom("C.def", "b = c", "def"),
            atom("D.xy", "x = y"),
        ],
        max_candidates=10,
        experiment_name="x",
    )
    assert candidates == []


def test_generator_zero_cap_yields_empty_list():
    assert generate_eq_trans_candidates([atom("A.ab", "a = b")], max_candidates=0, experiment_name="x") == []


def test_generator_is_deterministic_and_ids_are_stable():
    atoms = [atom("B.bc", "b = c"), atom("A.ab", "a = b"), atom("C.cd", "c = d")]
    first = generate_eq_trans_candidates(atoms, max_candidates=10, experiment_name="x")
    second = generate_eq_trans_candidates(atoms, max_candidates=10, experiment_name="x")
    assert first == second
    assert [candidate.candidate_id for candidate in first] == [candidate.candidate_id for candidate in second]


def test_distinct_parent_tuples_have_distinct_ids():
    candidates = generate_eq_trans_candidates(
        [atom("A.ab", "a = b"), atom("B.bc", "b = c"), atom("C.cd", "c = d")],
        max_candidates=10,
        experiment_name="x",
    )
    assert candidates[0].candidate_id != candidates[1].candidate_id
