from __future__ import annotations

import json

from solve.cli import main
from solve.promote import promote

from phase5a_helpers import promoted_classified_row, write_jsonl_dicts, write_phase5a_spec


def test_promote_empty_input_short_circuits_without_lean(tmp_path):
    spec_path, spec = write_phase5a_spec(tmp_path, "phase5a-empty")
    classified_path = write_jsonl_dicts(
        tmp_path / "value_classified.jsonl",
        [promoted_classified_row(spec, promotable=False)],
    )
    out_path = tmp_path / "promoted.jsonl"
    metrics_path = tmp_path / "promotion_metrics.json"

    metrics = promote(
        spec_path,
        repo=tmp_path,
        classified_path=classified_path,
        out_promoted=out_path,
        metrics_path=metrics_path,
    )

    assert out_path.exists()
    assert out_path.read_text(encoding="utf-8") == ""
    assert not list((tmp_path / "lean" / "Solve" / "Generated").glob("Promoted_*.lean"))
    assert metrics.promoted_count == 0
    assert metrics.promoted_module is None
    assert metrics.rejected_replay_failure is False

    metric_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metric_payload["promoted_count"] == 0
    assert metric_payload["rejected_replay_failure"] is False


def test_promote_empty_input_cli_exits_zero(tmp_path):
    spec_path, spec = write_phase5a_spec(tmp_path, "phase5a-empty-cli")
    classified_path = write_jsonl_dicts(
        tmp_path / "value_classified.jsonl",
        [promoted_classified_row(spec, promotable=False)],
    )
    out_path = tmp_path / "promoted.jsonl"
    metrics_path = tmp_path / "promotion_metrics.json"

    exit_code = main(
        [
            "promote",
            str(spec_path),
            "--classified",
            str(classified_path),
            "--out",
            str(out_path),
            "--metrics",
            str(metrics_path),
            "--repo",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert out_path.exists()
    assert out_path.read_text(encoding="utf-8") == ""
