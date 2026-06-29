from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from solve.cli import main
from solve.experiments.spec import load_experiment_spec
from solve.loop import run_control


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.lean
def test_cli_classifies_small_run0_value_set(tmp_path):
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

    out_path = tmp_path / "value_classified.jsonl"
    metrics_path = tmp_path / "value_metrics.json"
    exit_code = main(
        [
            "classify-value",
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
            "--novelty-timeout",
            "60",
            "--repo",
            str(ROOT),
        ]
    )

    assert exit_code == 0
    classified = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert classified
    for row in classified:
        assert row["structural_packaging"] is True
        assert row["structural_packaging_reason"].startswith("And.intro")
        assert row["ingredient_trivial_by_automation"] is True
        assert row["promotable"] is False
        assert row["novelty_classification"] in {
            "novel_in_imported_env",
            "existing_defeq_duplicate",
        }
        assert row["from_scratch_closure"] in {"closed", "not_closed", "timeout", "error"}

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics["counts_by_promotable"]["true"] == 0
    assert metrics["counts_by_structural_packaging"]["true"] == len(classified)
