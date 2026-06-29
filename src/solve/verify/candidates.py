"""Strict models for generated structural-control candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from solve.grammar.operators import OPERATORS


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


CandidateOperator = Literal["And.intro", "Eq.symm", "Eq.trans", "congrArg", "Iff.intro", "Iff.mp", "Iff.mpr"]

# The registry records Lean proof-argument arity. The 5d Iff.mp/Iff.mpr
# generators synthesize implication theorems from a single iff theorem parent.
_GENERATOR_ARITY_OVERRIDES = {"Iff.mp": 1, "Iff.mpr": 1}


def _generator_arity(operator: str) -> int:
    if operator in _GENERATOR_ARITY_OVERRIDES:
        return _GENERATOR_ARITY_OVERRIDES[operator]
    return OPERATORS[operator].arity


def make_candidate_id(operator: str, parents: tuple[str, ...], depth: int) -> str:
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
    operator: CandidateOperator
    parents: tuple[str, ...]
    depth: int = Field(..., ge=1, le=1)
    generated_theorem_name: str = Field(..., min_length=1)
    parent_atom_kinds: tuple[str, ...]
    statement: str | None = None
    proof_term: str | None = None

    @model_validator(mode="after")
    def operator_contract(self) -> "GeneratedCandidate":
        expected_arity = _generator_arity(self.operator)
        if len(self.parents) != expected_arity:
            raise ValueError(f"{self.operator} candidates require {expected_arity} parents")
        if len(self.parent_atom_kinds) != expected_arity:
            raise ValueError(f"{self.operator} candidates require {expected_arity} parent atom kinds")

        if self.operator == "And.intro":
            if self.statement is not None or self.proof_term is not None:
                raise ValueError("And.intro candidates must not carry typed statement/proof fields")
            return self

        if self.statement is None or not self.statement.strip():
            raise ValueError(f"{self.operator} candidates require a non-empty statement")
        if self.proof_term is None or not self.proof_term.strip():
            raise ValueError(f"{self.operator} candidates require a non-empty proof_term")
        return self


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
