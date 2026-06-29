from __future__ import annotations

import pytest

from solve.lean.replay import build_modules, replay_file
from solve.promote import promote
from solve.verify.promoted import read_promoted_jsonl

from phase5a_helpers import (
    ROOT,
    cleanup_generated_for,
    promoted_classified_row,
    promoted_module_name,
    safe_suffix,
    source_module_name,
    write_jsonl_dicts,
    write_phase5a_spec,
    write_source_run_control_module,
)


@pytest.mark.lean
def test_promote_synthetic_replays_generated_module(tmp_path):
    spec_name = "phase5a-promote"
    cleanup_generated_for(spec_name)
    try:
        spec_path, spec = write_phase5a_spec(tmp_path, spec_name)
        write_source_run_control_module(spec)
        build_modules(ROOT, [source_module_name(spec)], timeout=300)
        classified_path = write_jsonl_dicts(
            tmp_path / "value_classified.jsonl",
            [promoted_classified_row(spec)],
        )

        metrics = promote(
            spec_path,
            repo=ROOT,
            classified_path=classified_path,
            out_promoted=tmp_path / "promoted.jsonl",
            metrics_path=tmp_path / "promotion_metrics.json",
            timeout=300,
        )

        records = read_promoted_jsonl(tmp_path / "promoted.jsonl")
        module_path = ROOT / "lean" / "Solve" / "Generated" / f"Promoted_{safe_suffix(spec.name)}.lean"
        replay = replay_file(module_path, cwd=ROOT, timeout=300)

        assert len(records) == 1
        assert records[0].promoted_module == promoted_module_name(spec)
        assert module_path.exists()
        assert replay.returncode == 0
        assert "sorryAx" not in replay.stdout
        assert "sorryAx" not in replay.stderr
        assert metrics.promoted_count == 1
        assert metrics.promoted_module == promoted_module_name(spec)
        assert metrics.rejected_replay_failure is False
    finally:
        cleanup_generated_for(spec_name)


@pytest.mark.lean
def test_promote_broken_synthetic_rejects_whole_epoch(tmp_path):
    spec_name = "phase5a-broken"
    cleanup_generated_for(spec_name)
    try:
        spec_path, spec = write_phase5a_spec(tmp_path, spec_name)
        write_source_run_control_module(spec)
        build_modules(ROOT, [source_module_name(spec)], timeout=300)
        classified_path = write_jsonl_dicts(
            tmp_path / "value_classified.jsonl",
            [
                promoted_classified_row(
                    spec,
                    proof_term="And.intro (@Nonexistent.foo) (@Nat.zero_lt_one)",
                )
            ],
        )
        out_path = tmp_path / "promoted.jsonl"

        with pytest.raises(RuntimeError, match="promoted module (replay|build) failed"):
            promote(
                spec_path,
                repo=ROOT,
                classified_path=classified_path,
                out_promoted=out_path,
                metrics_path=tmp_path / "promotion_metrics.json",
                timeout=300,
            )

        module_path = ROOT / "lean" / "Solve" / "Generated" / f"Promoted_{safe_suffix(spec.name)}.lean"
        assert not out_path.exists()
        assert not module_path.exists()
    finally:
        cleanup_generated_for(spec_name)
