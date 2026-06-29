"""Receipt models for replay-retained candidates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AutomationClassification = Literal[
    "trivial_by_automation",
    "not_trivial_under_bound",
    "automation_error",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReplayResult(StrictModel):
    command: list[str] = Field(..., min_length=1)
    exit_code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def accepted(self) -> bool:
        return self.exit_code == 0 and "sorryAx" not in self.stdout and "sorryAx" not in self.stderr


class CandidateReceipt(StrictModel):
    record_id: str
    experiment_id: str
    toolchain: str
    imports: list[str]
    statement: str
    proof_term: str
    generated_theorem_name: str
    parents: list[str]
    operator: str
    depth: int = Field(..., ge=0)
    normalized_statement_hash: str
    axioms_used: list[str] = Field(default_factory=list)
    replay: ReplayResult
    novelty_classification: Literal["unknown", "existing_defeq_duplicate", "novel_in_imported_env"] = "unknown"
    interestingness_classification: Literal["unknown", "trivial", "nontrivial", "downstream_used"] = "unknown"
    automation_attempted: list[str] = Field(default_factory=list)
    automation_closed_by: str | None = None
    automation_heartbeat_budget: int | None = Field(default=None, ge=0)
    automation_step_budget: int | None = Field(default=None, ge=0)
    automation_classification: AutomationClassification | None = None

    @property
    def replay_accepted(self) -> bool:
        return self.replay.accepted


def write_jsonl(path: str | Path, receipts: list[CandidateReceipt]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for receipt in receipts:
            fh.write(json.dumps(receipt.model_dump(mode="json"), sort_keys=True) + "\n")
    return path


def read_jsonl(path: str | Path) -> list[CandidateReceipt]:
    receipts: list[CandidateReceipt] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                receipts.append(CandidateReceipt.model_validate_json(line))
            except Exception as exc:  # pragma: no cover - message wrapping only
                raise ValueError(f"invalid receipt JSONL at line {line_no}: {exc}") from exc
    return receipts
