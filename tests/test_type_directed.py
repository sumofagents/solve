from __future__ import annotations

from solve.grammar.type_directed import (
    closed_equality,
    closed_iff,
    closed_implication,
    has_omitted_pp,
    is_bare_proposition,
)
from solve.lean.atoms import AtomRecord


def atom(
    name: str = "Test.atom",
    type_pp: str = "a = b",
    kind: str = "theorem",
    binder_count: int | None = 0,
    arity: int | None = 0,
) -> AtomRecord:
    return AtomRecord(
        name=name,
        kind=kind,
        type_pp=type_pp,
        type_hash=f"hash-{name}",
        binder_count=binder_count,
        arity=arity,
        module="Test",
        axioms=[],
    )


def test_is_bare_proposition_zero():
    assert is_bare_proposition(atom(binder_count=0))


def test_is_bare_proposition_positive():
    assert not is_bare_proposition(atom(binder_count=1))


def test_is_bare_proposition_none_fail_closed():
    assert not is_bare_proposition(atom(binder_count=None))


def test_has_omitted_pp_true():
    assert has_omitted_pp(atom(type_pp="List.map ⋯ = []"))


def test_has_omitted_pp_false():
    assert not has_omitted_pp(atom(type_pp="a = b"))


def test_closed_equality_accepts_bare():
    assert closed_equality(atom(type_pp="a = b"))


def test_closed_equality_rejects_binders():
    assert not closed_equality(atom(type_pp="∀ x, f x = g x", binder_count=1))


def test_closed_equality_rejects_omitted():
    assert not closed_equality(atom(type_pp="f ⋯ = g ⋯"))


def test_closed_equality_rejects_iff():
    assert not closed_equality(atom(type_pp="P ↔ Q"))


def test_closed_iff_accepts_bare():
    assert closed_iff(atom(type_pp="P ↔ Q"))


def test_closed_iff_rejects_binders():
    assert not closed_iff(atom(type_pp="∀ x, P x ↔ Q x", binder_count=1))


def test_closed_implication_accepts_bare():
    assert closed_implication(atom(type_pp="P → Q"))


def test_closed_implication_rejects_binders():
    assert not closed_implication(atom(type_pp="∀ x, P x → Q x", binder_count=1))
