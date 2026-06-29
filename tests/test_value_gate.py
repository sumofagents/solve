from __future__ import annotations

import json
from pathlib import Path

from solve.lean.triviality import AttemptResult
from solve.lean.value import classify_value, compose_value_gate
from solve.verify.receipts import CandidateReceipt, ReplayResult


ROOT = Path(__file__).resolve().parents[1]


def test_value_gate_truth_table():
    assert (
        compose_value_gate(
            truth=True,
            novelty_classification="novel_in_imported_env",
            structural_packaging=False,
            ingredient_trivial_by_automation=False,
            downstream_used=None,
        ).promotable
        is True
    )
    assert (
        compose_value_gate(
            truth=True,
            novelty_classification="novel_in_imported_env",
            structural_packaging=True,
            ingredient_trivial_by_automation=False,
            downstream_used=None,
        ).promotable
        is False
    )
    assert (
        compose_value_gate(
            truth=True,
            novelty_classification="existing_defeq_duplicate",
            structural_packaging=False,
            ingredient_trivial_by_automation=False,
            downstream_used=None,
        ).promotable
        is False
    )
    assert (
        compose_value_gate(
            truth=False,
            novelty_classification="novel_in_imported_env",
            structural_packaging=False,
            ingredient_trivial_by_automation=False,
            downstream_used=None,
        ).promotable
        is False
    )


def test_interesting_is_false_without_downstream_use():
    gate = compose_value_gate(
        truth=True,
        novelty_classification="novel_in_imported_env",
        structural_packaging=False,
        ingredient_trivial_by_automation=False,
        downstream_used=None,
    )

    assert gate.promotable is True
    assert gate.interesting is False
    assert gate.interestingness_classification == "unknown"


def test_gate_is_fail_closed_on_probe_uncertainty():
    """Probe errors (None) must block promotion even when novelty=novel."""
    assert compose_value_gate(
        truth=True,
        novelty_classification="novel_in_imported_env",
        structural_packaging=None,
        ingredient_trivial_by_automation=False,
        downstream_used=None,
    ).promotable is False

    assert compose_value_gate(
        truth=True,
        novelty_classification="novel_in_imported_env",
        structural_packaging=False,
        ingredient_trivial_by_automation=None,
        downstream_used=None,
    ).promotable is False


def test_value_classifier_skips_probes_for_not_retained_receipts(monkeypatch, tmp_path):
    receipt = CandidateReceipt(
        record_id="cand_not_retained",
        experiment_id="run0-nat-control",
        toolchain="leanprover/lean4:v4.31.0",
        imports=["Mathlib.Data.Nat.Basic"],
        statement="True",
        proof_term="by trivial",
        generated_theorem_name="Solve.Generated.RunControl.not_retained",
        parents=["Nat.zero_lt_one", "Nat.succ_ne_zero"],
        operator="And.intro",
        depth=1,
        normalized_statement_hash="sha256:not-retained",
        axioms_used=[],
        replay=ReplayResult(command=["lake", "env", "lean", "run.lean"], exit_code=1),
        novelty_classification="unknown",
        interestingness_classification="trivial",
    )
    receipts_path = tmp_path / "receipts.jsonl"
    receipts_path.write_text(json.dumps(receipt.model_dump(mode="json"), sort_keys=True) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "solve.lean.value._run_import_probe",
        lambda **kwargs: AttemptResult(tactic="import_probe", exit_code=0),
    )
    monkeypatch.setattr(
        "solve.lean.value.probe_structural_packaging_details",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("structural probe called")),
    )
    monkeypatch.setattr(
        "solve.lean.value.probe_novelty_batch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("novelty probe called")),
    )

    metrics = classify_value(
        ROOT / "experiments" / "run0_nat_control.yaml",
        repo=ROOT,
        receipts_path=receipts_path,
        out_path=tmp_path / "value.jsonl",
        metrics_path=tmp_path / "metrics.json",
    )

    assert metrics.retained_receipts_classified == 0
    assert metrics.skipped_not_retained_count == 1
    assert (tmp_path / "value.jsonl").read_text(encoding="utf-8") == ""
