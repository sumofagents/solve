from pathlib import Path

import pytest
import yaml

from solve.experiments.spec import load_experiment_spec
from solve.loop import run_control
from solve.verify.candidates import read_metrics
from solve.verify.receipts import read_jsonl


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.lean
def test_run_control_run0_smoke_seed_limit_5(tmp_path):
    base = load_experiment_spec(ROOT / "experiments" / "run0_nat_control.yaml")
    spec = base.model_copy(update={"corpus": base.corpus.model_copy(update={"seed_limit": 5})})
    spec_path = tmp_path / "run0_seed5.yaml"
    spec_path.write_text(yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False), encoding="utf-8")

    receipts_path = tmp_path / "receipts.jsonl"
    metrics_path = tmp_path / "metrics.json"
    metrics = run_control(
        str(spec_path),
        repo=ROOT,
        out_receipts=receipts_path,
        out_metrics=metrics_path,
        max_candidates=3,
        timeout=300,
    )

    assert receipts_path.exists()
    receipts = read_jsonl(receipts_path)
    assert len(receipts) >= 1
    assert len(receipts) == metrics.candidate_count
    for receipt in receipts:
        assert receipt.replay.accepted is True
        assert receipt.interestingness_classification == "trivial"
        assert isinstance(receipt.axioms_used, list)
        assert "sorryAx" not in receipt.replay.stdout
        assert "sorryAx" not in receipt.replay.stderr

    loaded_metrics = read_metrics(metrics_path)
    assert loaded_metrics == metrics
    assert metrics.retained_count == metrics.replay_accepted_count
    assert metrics.retained_count <= metrics.candidate_count
