from solve.grammar.and_intro import generate_and_intro_candidates
from solve.lean.atoms import AtomRecord


def atom(name: str, kind: str = "theorem") -> AtomRecord:
    return AtomRecord(
        name=name,
        kind=kind,
        type_pp="True",
        type_hash=f"hash-{name}",
        binder_count=0,
        arity=0,
        module="Test",
        axioms=[],
    )


def test_generator_emits_ordered_theorem_pairs():
    candidates = generate_and_intro_candidates(
        [atom("Nat.a"), atom("Nat.b"), atom("Nat.c")],
        max_candidates=10,
        experiment_name="run0-nat-control",
    )
    assert [candidate.parents for candidate in candidates] == [
        ("Nat.a", "Nat.b"),
        ("Nat.a", "Nat.c"),
        ("Nat.b", "Nat.a"),
        ("Nat.b", "Nat.c"),
        ("Nat.c", "Nat.a"),
        ("Nat.c", "Nat.b"),
    ]
    assert all(candidate.operator == "And.intro" for candidate in candidates)
    assert all(candidate.depth == 1 for candidate in candidates)


def test_generator_filters_non_theorems():
    candidates = generate_and_intro_candidates(
        [atom("Nat.a"), atom("Nat.defn", "def"), atom("Nat.ax", "axiom"), atom("Nat.b")],
        max_candidates=10,
        experiment_name="run0-nat-control",
    )
    assert [candidate.parents for candidate in candidates] == [("Nat.a", "Nat.b"), ("Nat.b", "Nat.a")]
    assert all(candidate.parent_atom_kinds == ("theorem", "theorem") for candidate in candidates)


def test_generator_zero_cap_yields_empty_list():
    assert generate_and_intro_candidates([atom("Nat.a"), atom("Nat.b")], max_candidates=0, experiment_name="x") == []


def test_generator_is_deterministic_and_ids_are_stable():
    atoms = [atom("Nat.a"), atom("Nat.b"), atom("Nat.c")]
    first = generate_and_intro_candidates(atoms, max_candidates=4, experiment_name="run0-nat-control")
    second = generate_and_intro_candidates(atoms, max_candidates=4, experiment_name="run0-nat-control")
    assert first == second
    assert [candidate.candidate_id for candidate in first] == [candidate.candidate_id for candidate in second]
    assert all(candidate.candidate_id.startswith("cand_") for candidate in first)
    assert all(len(candidate.candidate_id) == len("cand_") + 16 for candidate in first)


def test_reverse_order_candidates_have_distinct_ids():
    candidates = generate_and_intro_candidates(
        [atom("Nat.a"), atom("Nat.b")],
        max_candidates=2,
        experiment_name="run0-nat-control",
    )
    assert [candidate.parents for candidate in candidates] == [("Nat.a", "Nat.b"), ("Nat.b", "Nat.a")]
    assert candidates[0].candidate_id != candidates[1].candidate_id


def test_generated_theorem_name_indices_are_dense():
    candidates = generate_and_intro_candidates(
        [atom("Nat.a"), atom("Nat.b"), atom("Nat.c")],
        max_candidates=5,
        experiment_name="run0-nat-control",
    )
    assert [candidate.generated_theorem_name for candidate in candidates] == [
        "Solve.Generated.RunControl.solve_generated_0",
        "Solve.Generated.RunControl.solve_generated_1",
        "Solve.Generated.RunControl.solve_generated_2",
        "Solve.Generated.RunControl.solve_generated_3",
        "Solve.Generated.RunControl.solve_generated_4",
    ]
