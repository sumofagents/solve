from pathlib import Path

from solve.experiments.spec import load_experiment_spec
from solve.lean.codegen import write_run_control_module
from solve.verify.candidates import GeneratedCandidate, make_candidate_id


ROOT = Path(__file__).resolve().parents[1]


def typed_candidate(index: int, operator: str, parents: tuple[str, ...], statement: str, proof_term: str) -> GeneratedCandidate:
    return GeneratedCandidate(
        candidate_id=make_candidate_id(operator, parents, 1),
        operator=operator,
        parents=parents,
        depth=1,
        generated_theorem_name=f"Solve.Generated.RunControl.solve_generated_{index}",
        parent_atom_kinds=tuple("theorem" for _ in parents),
        statement=statement,
        proof_term=proof_term,
    )


def test_write_run_control_module_emits_exact_typed_operator_theorems(tmp_path):
    spec = load_experiment_spec(ROOT / "experiments" / "run0_nat_control.yaml")
    candidates = [
        typed_candidate(0, "Eq.symm", ("A.eq",), "b = a", "Eq.symm @A.eq"),
        typed_candidate(1, "Eq.trans", ("A.eq", "B.eq"), "a = c", "Eq.trans @A.eq @B.eq"),
        typed_candidate(2, "congrArg", ("F.f", "A.eq"), "F.f a = F.f b", "congrArg @F.f @A.eq"),
        typed_candidate(3, "Iff.intro", ("A.mp", "A.mpr"), "P ↔ Q", "Iff.intro @A.mp @A.mpr"),
        typed_candidate(4, "Iff.mp", ("A.iff",), "P → Q", "Iff.mp @A.iff"),
        typed_candidate(5, "Iff.mpr", ("A.iff",), "Q → P", "Iff.mpr @A.iff"),
    ]

    path = write_run_control_module(candidates, repo=tmp_path, spec=spec, module_suffix="typed")
    text = path.read_text(encoding="utf-8")

    assert text == """import Mathlib.Data.Nat.Basic

-- Lean requires theorem declarations to carry an explicit type; defs with @parents preserve inferred And.intro types.
namespace Solve.Generated.RunControl

theorem solve_generated_0 : b = a := Eq.symm @A.eq
#check Solve.Generated.RunControl.solve_generated_0
#print axioms Solve.Generated.RunControl.solve_generated_0

theorem solve_generated_1 : a = c := Eq.trans @A.eq @B.eq
#check Solve.Generated.RunControl.solve_generated_1
#print axioms Solve.Generated.RunControl.solve_generated_1

theorem solve_generated_2 : F.f a = F.f b := congrArg @F.f @A.eq
#check Solve.Generated.RunControl.solve_generated_2
#print axioms Solve.Generated.RunControl.solve_generated_2

theorem solve_generated_3 : P ↔ Q := Iff.intro @A.mp @A.mpr
#check Solve.Generated.RunControl.solve_generated_3
#print axioms Solve.Generated.RunControl.solve_generated_3

theorem solve_generated_4 : P → Q := Iff.mp @A.iff
#check Solve.Generated.RunControl.solve_generated_4
#print axioms Solve.Generated.RunControl.solve_generated_4

theorem solve_generated_5 : Q → P := Iff.mpr @A.iff
#check Solve.Generated.RunControl.solve_generated_5
#print axioms Solve.Generated.RunControl.solve_generated_5

end Solve.Generated.RunControl
"""
