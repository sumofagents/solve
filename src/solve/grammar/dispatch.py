"""Grammar generator dispatch."""

from __future__ import annotations

from solve.grammar.and_intro import generate_and_intro_candidates
from solve.grammar.congr_arg import generate_congr_arg_candidates
from solve.grammar.eq_symm import generate_eq_symm_candidates
from solve.grammar.eq_trans import generate_eq_trans_candidates
from solve.grammar.iff_intro import generate_iff_intro_candidates
from solve.grammar.iff_mp import generate_iff_mp_candidates
from solve.grammar.iff_mpr import generate_iff_mpr_candidates
from solve.grammar.operators import require_known_operator
from solve.lean.atoms import AtomRecord
from solve.verify.candidates import GeneratedCandidate


_UNIMPLEMENTED_REGISTERED_OPERATORS = frozenset({"Eq.refl", "congrFun", "Eq.subst", "Or.inl", "Or.inr"})


def generate_for_operator(
    operator: str,
    atoms: list[AtomRecord],
    *,
    max_candidates: int,
    experiment_name: str,
) -> list[GeneratedCandidate]:
    require_known_operator(operator)
    generators = {
        "And.intro": generate_and_intro_candidates,
        "Eq.symm": generate_eq_symm_candidates,
        "Eq.trans": generate_eq_trans_candidates,
        "congrArg": generate_congr_arg_candidates,
        "Iff.intro": generate_iff_intro_candidates,
        "Iff.mp": generate_iff_mp_candidates,
        "Iff.mpr": generate_iff_mpr_candidates,
    }
    generator = generators.get(operator)
    if generator is None:
        if operator in _UNIMPLEMENTED_REGISTERED_OPERATORS:
            return []
        raise ValueError(f"no generator implemented for operator {operator!r}")
    return generator(atoms, max_candidates=max_candidates, experiment_name=experiment_name)
