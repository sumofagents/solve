"""Strict models for generated structural-control candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def make_candidate_id(operator: str, parents: tuple[str, str], depth: int) -> str:
    """Return the phase-2 stable candidate id."""
    payload = json.dumps(
        {
            "operator": operator,
            "parents": list(parents),
            "depth": depth,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"cand_{digest}"


class GeneratedCandidate(StrictFrozenModel):
    candidate_id: str = Field(..., min_length=1)
    operator: Literal["And.intro"]
    parents: tuple[str, str]
    depth: int = Field(..., ge=1, le=1)
    generated_theorem_name: str = Field(..., min_length=1)
    parent_atom_kinds: tuple[str, str]


class RunControlMetrics(StrictFrozenModel):
    experiment_id: str = Field(..., min_length=1)
    toolchain: str = Field(..., min_length=1)
    imports: list[str]
    candidate_count: int = Field(..., ge=0)
    replay_attempted_count: int = Field(..., ge=0)
    replay_accepted_count: int = Field(..., ge=0)
    retained_count: int = Field(..., ge=0)
    trivial_count: int = Field(..., ge=0)
    structural_count: int = Field(..., ge=0)
    started_at_iso: str | None
    finished_at_iso: str | None
    duration_seconds: float = Field(..., ge=0)
    out_receipts: str

    @model_validator(mode="after")
    def consistent_counts(self) -> "RunControlMetrics":
        if self.replay_attempted_count > self.candidate_count:
            raise ValueError("replay_attempted_count cannot exceed candidate_count")
        if self.replay_accepted_count > self.replay_attempted_count:
            raise ValueError("replay_accepted_count cannot exceed replay_attempted_count")
        if self.retained_count != self.replay_accepted_count:
            raise ValueError("retained_count must equal replay_accepted_count")
        if self.trivial_count != self.retained_count:
            raise ValueError("trivial_count must equal retained_count")
        if self.structural_count != self.retained_count:
            raise ValueError("structural_count must equal retained_count")
        return self


def write_metrics(path: str | Path, metrics: RunControlMetrics) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metrics.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def read_metrics(path: str | Path) -> RunControlMetrics:
    return RunControlMetrics.model_validate_json(Path(path).read_text(encoding="utf-8"))
