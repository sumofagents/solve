from __future__ import annotations

from solve.grammar.congr_arg import generate_congr_arg_candidates
from solve.lean.atoms import AtomRecord


def atom(name: str, kind: str, type_pp: str, arity: int | None = 0) -> AtomRecord:
    return AtomRecord(
        name=name,
        kind=kind,
        type_pp=type_pp,
        type_hash=f"hash-{name}",
        binder_count=arity,
        arity=arity,
        module="Test",
        axioms=[],
    )


def test_generator_emits_ordered_function_equality_pairs():
    candidates = generate_congr_arg_candidates(
        [
            atom("F.g", "theorem", "Nat → Nat", 1),
            atom("F.f", "def", "Nat → Nat", 1),
            atom("E.h2", "theorem", "b = c"),
            atom("E.h1", "theorem", "a = b"),
        ],
        max_candidates=10,
        experiment_name="x",
    )
    assert [candidate.parents for candidate in candidates] == [
        ("F.f", "E.h1"),
        ("F.f", "E.h2"),
        ("F.g", "E.h1"),
        ("F.g", "E.h2"),
    ]
    assert candidates[0].statement == "F.f a = F.f b"
    assert all(candidate.operator == "congrArg" for candidate in candidates)


def test_generator_filters_non_functions_and_wrong_equality_shapes():
    candidates = generate_congr_arg_candidates(
        [
            atom("F.not_function", "def", "Nat", 0),
            atom("F.axiom", "axiom", "Nat → Nat", 1),
            atom("E.bad", "theorem", "P ↔ Q"),
            atom("F.f", "def", "Nat → Nat", 1),
            atom("E.h", "theorem", "a = b"),
        ],
        max_candidates=10,
        experiment_name="x",
    )
    assert [candidate.parents for candidate in candidates] == [("F.f", "E.h")]
    assert candidates[0].parent_atom_kinds == ("def", "theorem")


def test_generator_zero_cap_yields_empty_list():
    assert generate_congr_arg_candidates([], max_candidates=0, experiment_name="x") == []


def test_generator_is_deterministic_and_ids_are_stable():
    atoms = [
        atom("F.f", "def", "Nat → Nat", 1),
        atom("E.h1", "theorem", "a = b"),
        atom("E.h2", "theorem", "b = c"),
    ]
    first = generate_congr_arg_candidates(atoms, max_candidates=10, experiment_name="x")
    second = generate_congr_arg_candidates(atoms, max_candidates=10, experiment_name="x")
    assert first == second
    assert [candidate.candidate_id for candidate in first] == [candidate.candidate_id for candidate in second]


def test_distinct_parent_tuples_have_distinct_ids():
    candidates = generate_congr_arg_candidates(
        [
            atom("F.f", "def", "Nat → Nat", 1),
            atom("E.h1", "theorem", "a = b"),
            atom("E.h2", "theorem", "b = c"),
        ],
        max_candidates=10,
        experiment_name="x",
    )
    assert candidates[0].candidate_id != candidates[1].candidate_id
