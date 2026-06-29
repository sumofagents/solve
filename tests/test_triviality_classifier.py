from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from solve.cli import main
from solve.experiments.spec import load_experiment_spec
from solve.lean.triviality import (
    AUTOMATION_ERROR,
    NOT_TRIVIAL_UNDER_BOUND,
    TACTIC_BOUQUET,
    TRIVIAL_BY_AUTOMATION,
    AutomationBounds,
    classify_receipt,
    classify_triviality,
)
from solve.loop import run_control
from solve.verify.receipts import CandidateReceipt, ReplayResult


ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_KEYS = {
    "automation_attempted",
    "automation_closed_by",
    "automation_heartbeat_budget",
    "automation_step_budget",
    "automation_classification",
}


def _raw_receipt(statement: str, *, exit_code: int = 0) -> tuple[dict[str, object], CandidateReceipt]:
    receipt = CandidateReceipt(
        record_id="cand_test",
        experiment_id="run0-nat-control",
        toolchain="leanprover/lean4:v4.31.0",
        imports=["Mathlib.Data.Nat.Basic"],
        statement=statement,
        proof_term="by trivial",
        generated_theorem_name="Solve.Generated.RunControl.solve_generated_test",
        parents=["Nat.zero_lt_succ", "Nat.succ_ne_zero"],
        operator="And.intro",
        depth=1,
        normalized_statement_hash="sha256:test",
        axioms_used=[],
        replay=ReplayResult(
            command=["lake", "env", "lean", "lean/Solve/Generated/RunControl_run0_nat_control.lean"],
            exit_code=exit_code,
        ),
        novelty_classification="unknown",
        interestingness_classification="trivial",
    )
    raw = receipt.model_dump(mode="json")
    for key in AUTOMATION_KEYS:
        raw.pop(key, None)
    return raw, receipt


def _label_from_module(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    for label in TACTIC_BOUQUET:
        if f"\n  {label}\n" in text:
            return label
    return None


def _fake_runner(*, closes_by: str | None = None, timeout_on: str | None = None, seen: list[str] | None = None):
    def run(path: Path, repo: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
        del repo, timeout_seconds
        text = path.read_text(encoding="utf-8")
        if seen is not None:
            seen.append(text)
        label = _label_from_module(path)
        if label is None:
            return subprocess.CompletedProcess(
                args=["lake", "env", "lean", str(path)],
                returncode=0,
                stdout="",
                stderr="",
            )
        if label == timeout_on:
            raise subprocess.TimeoutExpired(cmd=["lake", "env", "lean", str(path)], timeout=1)
        return subprocess.CompletedProcess(
            args=["lake", "env", "lean", str(path)],
            returncode=0 if label == closes_by else 1,
            stdout="",
            stderr="" if label == closes_by else "unsolved goals",
        )

    return run


def _classify_with_fake(
    tmp_path: Path,
    statement: str,
    *,
    closes_by: str | None = None,
    timeout_on: str | None = None,
    seen: list[str] | None = None,
) -> dict[str, object]:
    raw, receipt = _raw_receipt(statement)
    spec = load_experiment_spec(ROOT / "experiments" / "run0_nat_control.yaml")
    bounds = AutomationBounds(heartbeat_budget=77, step_budget=11, timeout_seconds=3)
    return classify_receipt(
        raw,
        receipt=receipt,
        spec=spec,
        repo=ROOT,
        bounds=bounds,
        transient_dir=tmp_path,
        runner=_fake_runner(closes_by=closes_by, timeout_on=timeout_on, seen=seen),
    )


def test_classifier_records_simp_closure_and_preserves_receipt_fields(tmp_path):
    classified = _classify_with_fake(tmp_path, "1 = 1", closes_by="simp")

    assert classified["record_id"] == "cand_test"
    assert classified["parents"] == ["Nat.zero_lt_succ", "Nat.succ_ne_zero"]
    assert classified["novelty_classification"] == "unknown"
    assert classified["interestingness_classification"] == "trivial"
    assert classified["automation_attempted"] == ["simp"]
    assert classified["automation_closed_by"] == "simp"
    assert classified["automation_heartbeat_budget"] == 77
    assert classified["automation_step_budget"] == 11
    assert classified["automation_classification"] == TRIVIAL_BY_AUTOMATION


@pytest.mark.parametrize(
    ("statement", "closing_label"),
    [
        ("(True && True) = true", "decide"),
        ("∀ n : Nat, n + 0 = n", "omega"),
    ],
)
def test_classifier_attempts_until_decide_or_omega_succeeds(tmp_path, statement, closing_label):
    classified = _classify_with_fake(tmp_path, statement, closes_by=closing_label)
    expected_attempted = list(TACTIC_BOUQUET[: TACTIC_BOUQUET.index(closing_label) + 1])

    assert classified["automation_attempted"] == expected_attempted
    assert classified["automation_closed_by"] == closing_label
    assert classified["automation_classification"] == TRIVIAL_BY_AUTOMATION


def test_classifier_reports_not_trivial_when_bouquet_does_not_close(tmp_path):
    classified = _classify_with_fake(tmp_path, "False", closes_by=None)

    assert classified["automation_attempted"] == list(TACTIC_BOUQUET)
    assert classified["automation_closed_by"] is None
    assert classified["automation_classification"] == NOT_TRIVIAL_UNDER_BOUND


def test_timeout_path_is_fail_closed_and_reported_as_automation_error(tmp_path):
    classified = _classify_with_fake(tmp_path, "False", closes_by=None, timeout_on="simp")

    # simp times out => stop immediately; only simp was attempted.
    assert classified["automation_attempted"] == ["simp"]
    assert classified["automation_closed_by"] is None
    assert classified["automation_classification"] == AUTOMATION_ERROR


def test_infrastructure_error_dominates_even_if_later_tactic_closes(tmp_path):
    """If simp times out but decide would close, the classification must be
    automation_error, never trivial_by_automation. Fail-closed dominance."""
    classified = _classify_with_fake(tmp_path, "True", closes_by="decide", timeout_on="simp")

    # simp is attempted first and times out => stop immediately, automation_error.
    assert classified["automation_attempted"] == ["simp"]
    assert classified["automation_closed_by"] is None
    assert classified["automation_classification"] == AUTOMATION_ERROR


def test_classify_triviality_rejects_receipt_spec_mismatch(tmp_path):
    raw, _receipt = _raw_receipt("True")
    # mutate the receipt to claim a different experiment/toolchain
    raw["experiment_id"] = "some-other-experiment"
    receipts_path = tmp_path / "receipts.jsonl"
    receipts_path.write_text(json.dumps(raw, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="experiment_id"):
        classify_triviality(
            ROOT / "experiments" / "run0_nat_control.yaml",
            repo=ROOT,
            receipts_path=receipts_path,
            out_path=tmp_path / "classified.jsonl",
            metrics_path=tmp_path / "metrics.json",
            heartbeat_budget=100,
            step_budget=12,
            timeout_seconds=4,
            runner=_fake_runner(closes_by="decide"),
        )


def test_generated_module_uses_spec_imports_bounds_statement_and_single_tactic(tmp_path):
    seen: list[str] = []
    classified = _classify_with_fake(tmp_path, "1 = 1", closes_by="simp", seen=seen)

    assert classified["automation_closed_by"] == "simp"
    assert len(seen) == 1
    module = seen[0]
    assert "import Mathlib.Data.Nat.Basic" in module
    assert "set_option maxHeartbeats 77" in module
    assert "set_option maxRecDepth 11" in module
    assert "theorem candidate_cand_test_simp :" in module
    assert "  (1 = 1) := by" in module
    assert "\n  simp\n" in module
    assert "\n  decide\n" not in module


def test_classify_triviality_writes_classified_jsonl_and_metrics(tmp_path):
    retained_raw, _ = _raw_receipt("True")
    skipped_raw, _ = _raw_receipt("True", exit_code=1)
    receipts_path = tmp_path / "receipts.jsonl"
    receipts_path.write_text(
        json.dumps(retained_raw, sort_keys=True) + "\n" + json.dumps(skipped_raw, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    out_path = tmp_path / "classified.jsonl"
    metrics_path = tmp_path / "metrics.json"

    metrics = classify_triviality(
        ROOT / "experiments" / "run0_nat_control.yaml",
        repo=ROOT,
        receipts_path=receipts_path,
        out_path=out_path,
        metrics_path=metrics_path,
        heartbeat_budget=100,
        step_budget=12,
        timeout_seconds=4,
        runner=_fake_runner(closes_by="decide"),
    )

    rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["automation_attempted"] == ["simp", "decide"]
    assert rows[0]["automation_closed_by"] == "decide"
    assert metrics.total_receipts_read == 2
    assert metrics.retained_receipts_classified == 1
    assert metrics.skipped_not_retained_count == 1
    assert metrics.counts_by_automation_classification[TRIVIAL_BY_AUTOMATION] == 1
    assert json.loads(metrics_path.read_text(encoding="utf-8"))["automation_step_budget"] == 12


@pytest.mark.lean
def test_cli_classifies_small_capped_run0_set(tmp_path):
    base = load_experiment_spec(ROOT / "experiments" / "run0_nat_control.yaml")
    spec = base.model_copy(update={"corpus": base.corpus.model_copy(update={"seed_limit": 5})})
    spec_path = tmp_path / "run0_seed5.yaml"
    spec_path.write_text(yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False), encoding="utf-8")

    receipts_path = tmp_path / "receipts.jsonl"
    run_control(
        str(spec_path),
        repo=ROOT,
        out_receipts=receipts_path,
        out_metrics=tmp_path / "run0_metrics.json",
        max_candidates=2,
        timeout=300,
    )

    out_path = tmp_path / "classified.jsonl"
    metrics_path = tmp_path / "classification_metrics.json"
    exit_code = main(
        [
            "classify-triviality",
            str(spec_path),
            "--receipts",
            str(receipts_path),
            "--out",
            str(out_path),
            "--metrics",
            str(metrics_path),
            "--max-receipts",
            "2",
            "--timeout",
            "30",
            "--repo",
            str(ROOT),
        ]
    )

    assert exit_code == 0
    classified = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert classified
    for row in classified:
        assert row["automation_attempted"]
        assert row["automation_heartbeat_budget"] == 20_000
        assert row["automation_step_budget"] == 1_000
        assert row["automation_classification"] in {
            TRIVIAL_BY_AUTOMATION,
            NOT_TRIVIAL_UNDER_BOUND,
            AUTOMATION_ERROR,
        }
        assert row["novelty_classification"] == "unknown"
        assert row["interestingness_classification"] == "trivial"

    # Run0 structural And.intro candidates package deep library theorems as
    # conjunctions; restated as goals they are NOT closeable from scratch by
    # bounded automation. Empirically all are not_trivial_under_bound. Assert
    # at least that the filter produced a concrete verdict per row.
    assert all(row["automation_classification"] is not None for row in classified)


@pytest.mark.lean
def test_classifier_closes_genuinely_trivial_statement_against_real_lean(tmp_path):
    """Positive-path proof that the filter CAN close trivial goals.

    Run0 structural controls are not automation-trivial (they package deep
    lemmas). This test proves the filter itself works by feeding it a statement
    that bounded automation genuinely closes.
    """
    raw, receipt = _raw_receipt("True ∧ True")
    spec = load_experiment_spec(ROOT / "experiments" / "run0_nat_control.yaml")
    bounds = AutomationBounds(heartbeat_budget=20_000, step_budget=1_000, timeout_seconds=30)
    classified = classify_receipt(
        raw,
        receipt=receipt,
        spec=spec,
        repo=ROOT,
        bounds=bounds,
        transient_dir=tmp_path,
    )
    assert classified["automation_closed_by"] is not None
    assert classified["automation_classification"] == TRIVIAL_BY_AUTOMATION
