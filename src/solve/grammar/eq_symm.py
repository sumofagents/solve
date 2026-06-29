"""Deterministic Eq.symm typed candidate generation."""

from __future__ import annotations

from solve.grammar.type_shape import parse_equality, render_statement
from solve.lean.atoms import AtomRecord
from solve.verify.candidates import GeneratedCandidate, make_candidate_id


OPERATOR = "Eq.symm"
DEPTH = 1
RUN_CONTROL_NAMESPACE = "Solve.Generated.RunControl"


def generate_eq_symm_candidates(
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
    for atom, parsed in parsed_atoms:
        parents = (atom.name,)
        index = len(out)
        out.append(
            GeneratedCandidate(
                candidate_id=make_candidate_id(OPERATOR, parents, DEPTH),
                operator=OPERATOR,
                parents=parents,
                depth=DEPTH,
                generated_theorem_name=f"{RUN_CONTROL_NAMESPACE}.solve_generated_{index}",
                parent_atom_kinds=(atom.kind,),
                statement=render_statement(parsed, parsed.rhs, "=", parsed.lhs),
                proof_term=f"Eq.symm @{atom.name}",
            )
        )
        if len(out) == max_candidates:
            return out
    return out
