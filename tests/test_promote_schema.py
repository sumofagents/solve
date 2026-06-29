from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from solve.promote import make_promoted_record_id
from solve.verify.promoted import (
    PromotedAtomRecord,
    PromotionMetrics,
    read_promoted_jsonl,
    write_promoted_jsonl,
)
from solve.verify.receipts import CandidateReceipt, ReplayResult


def _record_payload() -> dict[str, object]:
    return {
        "record_id": make_promoted_record_id("cand_source", "solve_generated_0"),
        "experiment_id": "run0-nat-control",
        "toolchain": "leanprover/lean4:v4.31.0",
        "imports": ["Mathlib.Data.Nat.Basic"],
        "source_module": "Solve.Generated.RunControl_run0_nat_control",
        "source_record_id": "cand_source",
        "source_generated_theorem_name": "Solve.Generated.RunControl.solve_generated_0",
        "statement": "0 < 1 ∧ 0 < 1",
        "proof_term": "And.intro (@Nat.zero_lt_one) (@Nat.zero_lt_one)",
        "promoted_module": "Solve.Generated.Promoted_run0_nat_control",
        "local_name": "solve_generated_0",
        "fully_qualified_name": "Solve.Generated.Promoted_run0_nat_control.solve_generated_0",
        "promoted_at_iso": "2026-06-29T00:00:00Z",
    }


def test_promoted_atom_record_schema_and_stable_id():
    payload = _record_payload()
    record = PromotedAtomRecord.model_validate(payload)

    assert record.promoted is True
    assert record.epoch == 1
    assert record.record_id == make_promoted_record_id("cand_source", "solve_generated_0")
    assert make_promoted_record_id("cand_source", "solve_generated_0") == make_promoted_record_id(
        "cand_source", "solve_generated_0"
    )

    with pytest.raises(ValidationError):
        PromotedAtomRecord.model_validate({**payload, "unknown": "blocked"})
    with pytest.raises(ValidationError):
        PromotedAtomRecord.model_validate({**payload, "promoted": False})


def test_promotion_metrics_reject_negative_counts():
    with pytest.raises(ValidationError):
        PromotionMetrics(
            experiment_id="run0-nat-control",
            toolchain="leanprover/lean4:v4.31.0",
            promoted_count=-1,
            skipped_not_promotable_count=0,
            rejected_replay_failure=False,
            promoted_module=None,
            started_at_iso=None,
            finished_at_iso=None,
            duration_seconds=0.0,
            out_promoted="promoted.jsonl",
        )


def test_promoted_jsonl_roundtrip(tmp_path):
    record = PromotedAtomRecord.model_validate(_record_payload())
    path = write_promoted_jsonl(tmp_path / "promoted.jsonl", [record])

    assert read_promoted_jsonl(path) == [record]


def test_candidate_receipt_epoch_defaults_and_validates():
    base = {
        "record_id": "cand_receipt",
        "experiment_id": "run0-nat-control",
        "toolchain": "leanprover/lean4:v4.31.0",
        "imports": ["Mathlib.Data.Nat.Basic"],
        "statement": "0 < 1",
        "proof_term": "@Nat.zero_lt_one",
        "generated_theorem_name": "Solve.Generated.RunControl.solve_generated_0",
        "parents": ["Nat.zero_lt_one", "Nat.zero_lt_one"],
        "operator": "And.intro",
        "depth": 1,
        "normalized_statement_hash": "sha256:test",
        "axioms_used": [],
        "replay": ReplayResult(command=["lake", "env", "lean", "run.lean"], exit_code=0).model_dump(
            mode="json"
        ),
    }

    assert CandidateReceipt.model_validate({**base, "epoch": 0}).epoch == 0
    assert CandidateReceipt.model_validate({**base, "epoch": 1}).epoch == 1

    parsed = CandidateReceipt.model_validate_json(json.dumps(base))
    assert parsed.epoch == 0
