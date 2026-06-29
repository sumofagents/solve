"""Auditable operator registry for bounded candidate generation.

The registry is deliberately small. Python may choose operators from this list,
but Lean remains the final judge for every generated candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OperatorFamily = Literal["equality", "iff", "structural"]


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    arity: int
    family: OperatorFamily
    baseline: bool
    description: str


OPERATORS: dict[str, OperatorSpec] = {
    "Eq.refl": OperatorSpec("Eq.refl", 1, "equality", False, "Reflexive equality proof."),
    "Eq.symm": OperatorSpec("Eq.symm", 1, "equality", False, "Reverse an equality proof."),
    "Eq.trans": OperatorSpec("Eq.trans", 2, "equality", False, "Compose equalities with matching middle term."),
    "congrArg": OperatorSpec("congrArg", 2, "equality", False, "Lift equality through a function."),
    "congrFun": OperatorSpec("congrFun", 2, "equality", False, "Specialize equality between functions."),
    "Eq.subst": OperatorSpec("Eq.subst", 2, "equality", False, "Substitute along equality; tightly budgeted."),
    "Iff.intro": OperatorSpec("Iff.intro", 2, "iff", False, "Build iff from both implication directions."),
    "Iff.mp": OperatorSpec("Iff.mp", 2, "iff", False, "Use left-to-right direction of iff."),
    "Iff.mpr": OperatorSpec("Iff.mpr", 2, "iff", False, "Use right-to-left direction of iff."),
    "And.intro": OperatorSpec("And.intro", 2, "structural", True, "Structural baseline: packages two proofs."),
    "Or.inl": OperatorSpec("Or.inl", 1, "structural", True, "Structural baseline: weaken into left disjunct."),
    "Or.inr": OperatorSpec("Or.inr", 1, "structural", True, "Structural baseline: weaken into right disjunct."),
}

KNOWN_OPERATORS = frozenset(OPERATORS)


def require_known_operator(name: str) -> OperatorSpec:
    try:
        return OPERATORS[name]
    except KeyError as exc:
        known = ", ".join(sorted(KNOWN_OPERATORS))
        raise ValueError(f"unknown operator {name!r}; known operators: {known}") from exc


def baseline_operator_names() -> list[str]:
    return sorted(name for name, spec in OPERATORS.items() if spec.baseline)


def discovery_operator_names() -> list[str]:
    return sorted(name for name, spec in OPERATORS.items() if not spec.baseline)
