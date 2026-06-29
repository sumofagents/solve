"""Deterministic Iff.intro typed candidate generation."""

from __future__ import annotations

from solve.grammar.type_directed import closed_implication
from solve.grammar.type_shape import parse_implication, render_statement
from solve.lean.atoms import AtomRecord
from solve.verify.candidates import GeneratedCandidate, make_candidate_id


OPERATOR = "Iff.intro"
DEPTH = 1
RUN_CONTROL_NAMESPACE = "Solve.Generated.RunControl"


def generate_iff_intro_candidates(
    atoms: list[AtomRecord],
    *,
    max_candidates: int,
    experiment_name: str,
) -> list[GeneratedCandidate]:
    del experiment_name
    if max_candidates <= 0:
        return []

    implications = []
    for atom in sorted((atom for atom in atoms if closed_implication(atom)), key=lambda item: item.name):
        parsed = parse_implication(atom.type_pp)
        if parsed is None:
            continue
        implications.append((atom, parsed))

    out: list[GeneratedCandidate] = []
    for left_atom, left in implications:
        for right_atom, right in implications:
            if left.binders != right.binders:
                continue
            if left.lhs.strip() != right.rhs.strip() or left.rhs.strip() != right.lhs.strip():
                continue
            parents = (left_atom.name, right_atom.name)
            index = len(out)
            out.append(
                GeneratedCandidate(
                    candidate_id=make_candidate_id(OPERATOR, parents, DEPTH),
                    operator=OPERATOR,
                    parents=parents,
                    depth=DEPTH,
                    generated_theorem_name=f"{RUN_CONTROL_NAMESPACE}.solve_generated_{index}",
                    parent_atom_kinds=(left_atom.kind, right_atom.kind),
                    statement=render_statement(left, left.lhs, "↔", left.rhs),
                    proof_term=f"Iff.intro @{left_atom.name} @{right_atom.name}",
                )
            )
            if len(out) == max_candidates:
                return out
    return out
