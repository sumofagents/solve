import pytest

from solve.grammar.and_intro import generate_and_intro_candidates
from solve.grammar.dispatch import generate_for_operator
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


def test_dispatch_routes_and_intro_to_structural_generator():
    atoms = [atom("A.one"), atom("A.two")]
    dispatched = generate_for_operator("And.intro", atoms, max_candidates=10, experiment_name="x")
    direct = generate_and_intro_candidates(atoms, max_candidates=10, experiment_name="x")
    assert dispatched == direct


def test_dispatch_routes_typed_operator():
    candidates = generate_for_operator(
        "Eq.symm",
        [atom("A.eq").model_copy(update={"type_pp": "a = b"})],
        max_candidates=10,
        experiment_name="x",
    )
    assert [candidate.parents for candidate in candidates] == [("A.eq",)]


def test_dispatch_returns_empty_for_registered_out_of_scope_operator():
    assert generate_for_operator("Or.inl", [atom("A.one")], max_candidates=10, experiment_name="x") == []


def test_dispatch_unknown_operator_raises_value_error():
    with pytest.raises(ValueError, match="unknown operator"):
        generate_for_operator("Nope.op", [], max_candidates=10, experiment_name="x")
