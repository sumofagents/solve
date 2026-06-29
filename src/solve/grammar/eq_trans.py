"""Deterministic Eq.trans typed candidate generation."""

from __future__ import annotations

from solve.grammar.type_shape import parse_equality, render_statement
from solve.lean.atoms import AtomRecord
from solve.verify.candidates import GeneratedCandidate, make_candidate_id


OPERATOR = "Eq.trans"
DEPTH = 1
RUN_CONTROL_NAMESPACE = "Solve.Generated.RunControl"


def generate_eq_trans_candidates(
    atoms: list[AtomRecord],
    *,
    max_candidates: int,
    experiment_name: str,
) -> list[GeneratedCandidate]:
    del experiment_name
    if max_candidates <= 0:
        return []

    parsed_atoms = []
    for atom in sorted((atom for atom in atoms if atom.kind == "theorem"), key=lambda item: item.name):
        parsed = parse_equality(atom.type_pp)
        if parsed is not None:
            parsed_atoms.append((atom, parsed))

    out: list[GeneratedCandidate] = []
    for left_atom, left_parsed in parsed_atoms:
        for right_atom, right_parsed in parsed_atoms:
            if left_parsed.binders != right_parsed.binders:
                continue
            if left_parsed.rhs.strip() != right_parsed.lhs.strip():
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
                    statement=render_statement(left_parsed, left_parsed.lhs, "=", right_parsed.rhs),
                    proof_term=f"Eq.trans @{left_atom.name} @{right_atom.name}",
                )
            )
            if len(out) == max_candidates:
                return out
    return out
