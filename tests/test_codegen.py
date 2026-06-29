from pathlib import Path

from solve.experiments.spec import load_experiment_spec
from solve.lean.codegen import write_run_control_module
from solve.verify.candidates import GeneratedCandidate, make_candidate_id


ROOT = Path(__file__).resolve().parents[1]


def candidate(index: int, parents: tuple[str, str]) -> GeneratedCandidate:
    return GeneratedCandidate(
        candidate_id=make_candidate_id("And.intro", parents, 1),
        operator="And.intro",
        parents=parents,
        depth=1,
        generated_theorem_name=f"Solve.Generated.RunControl.solve_generated_{index}",
        parent_atom_kinds=("theorem", "theorem"),
    )


def test_write_run_control_module_contains_imports_candidates_and_axiom_prints(tmp_path):
    spec = load_experiment_spec(ROOT / "experiments" / "run0_nat_control.yaml")
    candidates = [
        candidate(0, ("Nat.zero_lt_succ", "Nat.succ_ne_zero")),
        candidate(1, ("Nat.succ_ne_zero", "Nat.zero_lt_succ")),
    ]
    path = write_run_control_module(candidates, repo=tmp_path, spec=spec, module_suffix=spec.name)
    text = path.read_text(encoding="utf-8")

    assert path == tmp_path / "lean" / "Solve" / "Generated" / "RunControl_run0_nat_control.lean"
    assert "import Mathlib.Data.Nat.Basic" in text
    assert "namespace Solve.Generated.RunControl" in text
    assert "end Solve.Generated.RunControl" in text
    assert "def solve_generated_0 := And.intro (@Nat.zero_lt_succ) (@Nat.succ_ne_zero)" in text
    assert "def solve_generated_1 := And.intro (@Nat.succ_ne_zero) (@Nat.zero_lt_succ)" in text
    assert "#print axioms Solve.Generated.RunControl.solve_generated_0" in text
    assert "#print axioms Solve.Generated.RunControl.solve_generated_1" in text


def test_write_run_control_module_sanitizes_hostile_suffix(tmp_path):
    spec = load_experiment_spec(ROOT / "experiments" / "run0_nat_control.yaml")
    path = write_run_control_module(
        [candidate(0, ("Nat.zero_lt_succ", "Nat.succ_ne_zero"))],
        repo=tmp_path,
        spec=spec,
        module_suffix="../ hostile/name 123?",
    )
    assert path.name == "RunControl_hostile_name_123.lean"
    assert " " not in path.name
    assert "/" not in path.name
