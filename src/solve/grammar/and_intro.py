"""Deterministic And.intro structural-control candidate generation."""

from __future__ import annotations

from solve.lean.atoms import AtomRecord
from solve.verify.candidates import GeneratedCandidate, make_candidate_id


OPERATOR = "And.intro"
DEPTH = 1
RUN_CONTROL_NAMESPACE = "Solve.Generated.RunControl"


def generate_and_intro_candidates(
    atoms: list[AtomRecord],
    *,
    max_candidates: int,
    experiment_name: str,
) -> list[GeneratedCandidate]:
    """Generate ordered theorem pairs for the phase-2 structural control."""
    del experiment_name
    if max_candidates <= 0:
        return []

    theorem_atoms = [atom for atom in atoms if atom.kind == "theorem"]
    out: list[GeneratedCandidate] = []
    for left in theorem_atoms:
        for right in theorem_atoms:
            if left.name == right.name:
                continue
            parents = (left.name, right.name)
            index = len(out)
            out.append(
                GeneratedCandidate(
                    candidate_id=make_candidate_id(OPERATOR, parents, DEPTH),
                    operator=OPERATOR,
                    parents=parents,
                    depth=DEPTH,
                    generated_theorem_name=f"{RUN_CONTROL_NAMESPACE}.solve_generated_{index}",
                    parent_atom_kinds=(left.kind, right.kind),
                )
            )
            if len(out) == max_candidates:
                return out
    return out
