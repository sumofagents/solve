"""Deterministic Iff.mp typed candidate generation."""

from __future__ import annotations

from solve.grammar.type_shape import parse_iff, render_statement
from solve.lean.atoms import AtomRecord
from solve.verify.candidates import GeneratedCandidate, make_candidate_id


OPERATOR = "Iff.mp"
DEPTH = 1
RUN_CONTROL_NAMESPACE = "Solve.Generated.RunControl"


def generate_iff_mp_candidates(
    atoms: list[AtomRecord],
    *,
    max_candidates: int,
    experiment_name: str,
) -> list[GeneratedCandidate]:
    del experiment_name
    if max_candidates <= 0:
        return []

    iff_atoms = []
    for atom in sorted((atom for atom in atoms if atom.kind == "theorem"), key=lambda item: item.name):
        parsed = parse_iff(atom.type_pp)
        if parsed is not None:
            iff_atoms.append((atom, parsed))

    out: list[GeneratedCandidate] = []
    for atom, parsed in iff_atoms:
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
                statement=render_statement(parsed, parsed.lhs, "→", parsed.rhs),
                proof_term=f"Iff.mp @{atom.name}",
            )
        )
        if len(out) == max_candidates:
            return out
    return out
