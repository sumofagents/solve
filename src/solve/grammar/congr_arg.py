"""Deterministic congrArg typed candidate generation."""

from __future__ import annotations

from solve.grammar.type_directed import closed_equality, congrarg_fn_head_matches
from solve.grammar.type_shape import lean_argument, parse_equality, render_statement
from solve.lean.atoms import AtomRecord
from solve.verify.candidates import GeneratedCandidate, make_candidate_id


OPERATOR = "congrArg"
DEPTH = 1
RUN_CONTROL_NAMESPACE = "Solve.Generated.RunControl"


def _function_atoms(atoms: list[AtomRecord]) -> list[AtomRecord]:
    return sorted(
        (
            atom
            for atom in atoms
            if atom.kind in {"def", "theorem"} and atom.arity is not None and atom.arity >= 1
        ),
        key=lambda item: item.name,
    )


def generate_congr_arg_candidates(
    atoms: list[AtomRecord],
    *,
    max_candidates: int,
    experiment_name: str,
) -> list[GeneratedCandidate]:
    del experiment_name
    if max_candidates <= 0:
        return []

    functions = _function_atoms(atoms)
    equalities = []
    for atom in sorted((atom for atom in atoms if closed_equality(atom)), key=lambda item: item.name):
        parsed = parse_equality(atom.type_pp)
        if parsed is None:
            continue
        equalities.append((atom, parsed))

    out: list[GeneratedCandidate] = []
    for function in functions:
        for equality_atom, equality in equalities:
            if not congrarg_fn_head_matches(function, equality):
                continue
            parents = (function.name, equality_atom.name)
            index = len(out)
            left = f"{function.name} {lean_argument(equality.lhs)}"
            right = f"{function.name} {lean_argument(equality.rhs)}"
            out.append(
                GeneratedCandidate(
                    candidate_id=make_candidate_id(OPERATOR, parents, DEPTH),
                    operator=OPERATOR,
                    parents=parents,
                    depth=DEPTH,
                    generated_theorem_name=f"{RUN_CONTROL_NAMESPACE}.solve_generated_{index}",
                    parent_atom_kinds=(function.kind, equality_atom.kind),
                    statement=render_statement(equality, left, "=", right),
                    proof_term=f"congrArg @{function.name} @{equality_atom.name}",
                )
            )
            if len(out) == max_candidates:
                return out
    return out
