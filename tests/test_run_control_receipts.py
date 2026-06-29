from pathlib import Path

import pytest
from pydantic import ValidationError

from solve.experiments.spec import load_experiment_spec
from solve.loop import _parse_checked_statements, _receipt_for
from solve.verify.candidates import GeneratedCandidate, RunControlMetrics, make_candidate_id, read_metrics, write_metrics
from solve.verify.receipts import ReplayResult


ROOT = Path(__file__).resolve().parents[1]


def test_receipt_and_metrics_for_retained_structural_control(tmp_path):
    spec = load_experiment_spec(ROOT / "experiments" / "run0_nat_control.yaml")
    parents = ("Nat.zero_lt_succ", "Nat.succ_ne_zero")
    candidate = GeneratedCandidate(
        candidate_id=make_candidate_id("And.intro", parents, 1),
        operator="And.intro",
        parents=parents,
        depth=1,
        generated_theorem_name="Solve.Generated.RunControl.solve_generated_0",
        parent_atom_kinds=("theorem", "theorem"),
    )
    statement = "True ∧ True"
    replay = ReplayResult(
        command=["lake", "env", "lean", "lean/Solve/Generated/RunControl_run0_nat_control.lean"],
        exit_code=0,
        stdout="'Solve.Generated.RunControl.solve_generated_0' does not depend on any axioms\n",
        stderr="",
    )

    receipt = _receipt_for(candidate=candidate, spec=spec, replay=replay, axioms_used=[], statement=statement)
    assert receipt.record_id == candidate.candidate_id
    assert receipt.statement == statement
    assert receipt.proof_term == "And.intro (@Nat.zero_lt_succ) (@Nat.succ_ne_zero)"
    assert receipt.replay_accepted is True
    assert receipt.novelty_classification == "unknown"
    assert receipt.interestingness_classification == "trivial"

    metrics = RunControlMetrics(
        experiment_id=spec.name,
        toolchain=spec.lean.toolchain,
        imports=list(spec.lean.imports),
        candidate_count=1,
        replay_attempted_count=1,
        replay_accepted_count=1,
        retained_count=1,
        trivial_count=1,
        structural_count=1,
        started_at_iso=None,
        finished_at_iso=None,
        duration_seconds=0.0,
        out_receipts=str(tmp_path / "receipts.jsonl"),
    )
    assert metrics.structural_count == metrics.retained_count
    assert metrics.trivial_count == metrics.retained_count
    assert metrics.retained_count == metrics.replay_accepted_count

    metrics_path = write_metrics(tmp_path / "metrics.json", metrics)
    assert read_metrics(metrics_path) == metrics


def test_metrics_reject_inconsistent_arithmetic(tmp_path):
    with pytest.raises(ValidationError, match="trivial_count must equal retained_count"):
        RunControlMetrics(
            experiment_id="run0-nat-control",
            toolchain="leanprover/lean4:v4.31.0",
            imports=["Mathlib.Data.Nat.Basic"],
            candidate_count=1,
            replay_attempted_count=1,
            replay_accepted_count=1,
            retained_count=1,
            trivial_count=0,
            structural_count=1,
            started_at_iso=None,
            finished_at_iso=None,
            duration_seconds=0.0,
            out_receipts=str(tmp_path / "receipts.jsonl"),
        )


def test_parse_multiline_check_statement():
    stdout = """Solve.Generated.RunControl.solve_generated_0.{u_1} :
  True ∧
    True
'Solve.Generated.RunControl.solve_generated_0' does not depend on any axioms
"""
    assert _parse_checked_statements(stdout) == {
        "Solve.Generated.RunControl.solve_generated_0": "True ∧ True"
    }
