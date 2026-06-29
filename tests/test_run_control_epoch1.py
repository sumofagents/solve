from __future__ import annotations

import pytest

from solve.lean.replay import build_modules
from solve.loop import run_control
from solve.promote import promote
from solve.verify.receipts import read_jsonl

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
def test_run_control_epoch1_extends_with_promoted_atoms(tmp_path):
    spec_name = "phase5a-epoch"
    cleanup_generated_for(spec_name)
    try:
        spec_path, spec = write_phase5a_spec(tmp_path, spec_name, seed_limit=5)
        write_source_run_control_module(spec)
        build_modules(ROOT, [source_module_name(spec)], timeout=300)
        classified_path = write_jsonl_dicts(
            tmp_path / "value_classified.jsonl",
            [promoted_classified_row(spec)],
        )
        promote(
            spec_path,
            repo=ROOT,
            classified_path=classified_path,
            out_promoted=tmp_path / "promoted.jsonl",
            metrics_path=tmp_path / "promotion_metrics.json",
            timeout=300,
        )

        receipts_path = tmp_path / "epoch1_receipts.jsonl"
        metrics = run_control(
            str(spec_path),
            repo=ROOT,
            out_receipts=receipts_path,
            out_metrics=tmp_path / "epoch1_metrics.json",
            max_candidates=25,
            timeout=300,
            epoch=1,
            extend_with=tmp_path / "promoted.jsonl",
        )

        epoch1_module = ROOT / "lean" / "Solve" / "Generated" / f"RunControl_{safe_suffix(f'{spec.name}_epoch1')}.lean"
        assert epoch1_module.exists()
        text = epoch1_module.read_text(encoding="utf-8")
        receipts = read_jsonl(receipts_path)
        promoted_fqn = f"{promoted_module_name(spec)}.solve_generated_0"

        assert f"import {promoted_module_name(spec)}" in text
        assert any(promoted_fqn in receipt.parents for receipt in receipts)
        assert all(receipt.replay.accepted for receipt in receipts)
        assert all(receipt.epoch == 1 for receipt in receipts)
        assert metrics.retained_count == metrics.replay_accepted_count

        epoch0_receipts = tmp_path / "epoch0_receipts.jsonl"
        run_control(
            str(spec_path),
            repo=ROOT,
            out_receipts=epoch0_receipts,
            out_metrics=tmp_path / "epoch0_metrics.json",
            max_candidates=1,
            timeout=300,
        )
        assert all(receipt.epoch == 0 for receipt in read_jsonl(epoch0_receipts))
    finally:
        cleanup_generated_for(spec_name)
