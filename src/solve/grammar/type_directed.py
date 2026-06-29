"""Type-directed atom selection predicates for typed grammar generation."""

from __future__ import annotations

from solve.grammar.type_shape import parse_equality, parse_iff, parse_implication
from solve.lean.atoms import AtomRecord


def is_bare_proposition(atom: AtomRecord) -> bool:
    """binder_count == 0. Fail-closed on None."""
    return atom.binder_count == 0


def has_omitted_pp(atom: AtomRecord) -> bool:
    """True if type_pp contains the ellipsis marker ⋯ (Lean omitted pretty-printing)."""
    return "⋯" in atom.type_pp


def closed_equality(atom: AtomRecord) -> bool:
    """kind=='theorem' AND is_bare_proposition AND not has_omitted_pp
    AND parse_equality(atom.type_pp) is not None."""
    return (
        atom.kind == "theorem"
        and is_bare_proposition(atom)
        and not has_omitted_pp(atom)
        and parse_equality(atom.type_pp) is not None
    )


def closed_iff(atom: AtomRecord) -> bool:
    """kind=='theorem' AND is_bare_proposition AND not has_omitted_pp
    AND parse_iff(atom.type_pp) is not None."""
    return (
        atom.kind == "theorem"
        and is_bare_proposition(atom)
        and not has_omitted_pp(atom)
        and parse_iff(atom.type_pp) is not None
    )


def closed_implication(atom: AtomRecord) -> bool:
    """kind=='theorem' AND is_bare_proposition AND not has_omitted_pp
    AND parse_implication(atom.type_pp) is not None."""
    return (
        atom.kind == "theorem"
        and is_bare_proposition(atom)
        and not has_omitted_pp(atom)
        and parse_implication(atom.type_pp) is not None
    )
