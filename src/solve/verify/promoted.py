"""Strict schemas and JSONL helpers for promoted atom records."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field, field_validator

from solve.verify.receipts import StrictModel


class PromotedAtomRecord(StrictModel):
    record_id: str
    experiment_id: str
    toolchain: str
    imports: list[str]
    source_module: str
    source_record_id: str
    source_generated_theorem_name: str
    statement: str
    proof_term: str
    promoted_module: str
    local_name: str
    fully_qualified_name: str
    promoted: bool = True
    epoch: int = Field(default=1, ge=1)
    promoted_at_iso: str

    @field_validator("promoted")
    @classmethod
    def promoted_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("promoted atom records must have promoted=true")
        return value


class PromotionMetrics(StrictModel):
    experiment_id: str
    toolchain: str
    promoted_count: int = Field(..., ge=0)
    skipped_not_promotable_count: int = Field(..., ge=0)
    rejected_replay_failure: bool
    promoted_module: str | None
    started_at_iso: str | None
    finished_at_iso: str | None
    duration_seconds: float = Field(..., ge=0)
    out_promoted: str


def write_promoted_jsonl(path: str | Path, records: list[PromotedAtomRecord]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n")
    return out


def read_promoted_jsonl(path: str | Path) -> list[PromotedAtomRecord]:
    records: list[PromotedAtomRecord] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(PromotedAtomRecord.model_validate_json(line))
            except Exception as exc:  # pragma: no cover - message wrapping only
                raise ValueError(f"invalid promoted JSONL at line {line_no}: {exc}") from exc
    return records


def write_promotion_metrics(path: str | Path, metrics: PromotionMetrics) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(metrics.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out
