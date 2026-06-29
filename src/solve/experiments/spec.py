"""Strict ExperimentSpec schema for bounded Lean/mathlib runs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from solve.grammar.operators import KNOWN_OPERATORS

UNBOUNDED_IMPORTS = {"Mathlib"}
DEDUP_POLICIES = {
    "syntactic_hash",
    "alpha_equivalence",
    "defeq",
    "defeq_imported_environment",
    "retained_defeq",
    "semantic_equiv_witness",
}

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_LEAN_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*(\.[A-Za-z_][A-Za-z0-9_']*)*$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LeanSpec(StrictModel):
    toolchain: str = Field(..., description="Pinned elan toolchain, e.g. leanprover/lean4:v4.31.0")
    imports: list[str] = Field(..., min_length=1)

    @field_validator("imports")
    @classmethod
    def bounded_imports(cls, imports: list[str]) -> list[str]:
        cleaned: list[str] = []
        for imp in imports:
            imp = imp.strip()
            if not imp:
                raise ValueError("imports may not contain empty module names")
            if imp in UNBOUNDED_IMPORTS:
                raise ValueError("unbounded import Mathlib is forbidden for normal experiments")
            if not _LEAN_MODULE_RE.match(imp):
                raise ValueError(
                    "imports must be plain Lean module names with no whitespace, comments, or commands"
                )
            cleaned.append(imp)
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("imports must be unique")
        return cleaned


class CorpusSpec(StrictModel):
    namespace_prefixes: list[str] = Field(..., min_length=1)
    seed_limit: int = Field(..., gt=0, le=10_000)
    max_binders: int = Field(..., ge=0, le=20)
    max_statement_chars: int = Field(..., gt=0, le=10_000)

    @field_validator("namespace_prefixes")
    @classmethod
    def nonempty_unique_prefixes(cls, prefixes: list[str]) -> list[str]:
        cleaned = [prefix.strip() for prefix in prefixes]
        if any(not prefix for prefix in cleaned):
            raise ValueError("namespace prefixes may not be empty")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("namespace prefixes must be unique")
        return cleaned


class GrammarSpec(StrictModel):
    operators: list[str] = Field(..., min_length=1)
    baseline_operators: list[str] = Field(default_factory=list)

    @field_validator("operators", "baseline_operators")
    @classmethod
    def known_unique_operators(cls, operators: list[str]) -> list[str]:
        cleaned = [op.strip() for op in operators]
        if any(not op for op in cleaned):
            raise ValueError("operator names may not be empty")
        unknown = sorted(set(cleaned) - KNOWN_OPERATORS)
        if unknown:
            raise ValueError(f"unknown operators: {', '.join(unknown)}")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("operators must be unique within each list")
        return cleaned

    @model_validator(mode="after")
    def disjoint_operator_sets(self) -> "GrammarSpec":
        overlap = sorted(set(self.operators) & set(self.baseline_operators))
        if overlap:
            raise ValueError(f"operators and baseline_operators overlap: {', '.join(overlap)}")
        return self

    @property
    def all_operators(self) -> list[str]:
        return [*self.operators, *self.baseline_operators]


class BoundsSpec(StrictModel):
    max_depth: int = Field(..., ge=1, le=10)
    promotion_depth: int = Field(..., ge=1, le=10)
    max_candidates_total: int = Field(..., gt=0, le=10_000_000)
    max_candidates_per_operator: int = Field(..., gt=0, le=1_000_000)
    verify_timeout_ms: int = Field(..., gt=0, le=300_000)

    @model_validator(mode="after")
    def promotion_not_shallower(self) -> "BoundsSpec":
        if self.promotion_depth < self.max_depth:
            raise ValueError("promotion_depth must be >= max_depth")
        return self


class DedupSpec(StrictModel):
    existing: str
    retained: str

    @field_validator("existing", "retained")
    @classmethod
    def known_policy(cls, policy: str) -> str:
        if policy not in DEDUP_POLICIES:
            known = ", ".join(sorted(DEDUP_POLICIES))
            raise ValueError(f"unknown dedup policy {policy!r}; known policies: {known}")
        return policy


class PromotionSpec(StrictModel):
    require_replay: bool = True
    require_not_existing_defeq: bool = True
    require_downstream_use_within_depth: int | None = Field(default=None, ge=1, le=10)


class ConsumerSpec(StrictModel):
    name: str

    @field_validator("name")
    @classmethod
    def nonempty(cls, name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("consumer name may not be empty")
        return name


class ConnectorsSpec(StrictModel):
    enabled: bool = False
    provider: str | None = None
    model_env: str | None = None

    @model_validator(mode="after")
    def provider_only_metadata(self) -> "ConnectorsSpec":
        if not self.enabled and (self.provider or self.model_env):
            raise ValueError("disabled connectors must not carry provider/model_env metadata")
        return self


class ExperimentSpec(StrictModel):
    version: Literal[1]
    name: str
    lean: LeanSpec
    corpus: CorpusSpec
    grammar: GrammarSpec
    bounds: BoundsSpec
    dedup: DedupSpec
    promotion: PromotionSpec
    consumer: ConsumerSpec
    connectors: ConnectorsSpec = Field(default_factory=ConnectorsSpec)

    @field_validator("name")
    @classmethod
    def portable_name(cls, name: str) -> str:
        if not _NAME_RE.match(name):
            raise ValueError("name must be lowercase kebab/snake style")
        return name

    @model_validator(mode="after")
    def enforce_replay_retention_gate(self) -> "ExperimentSpec":
        if not self.promotion.require_replay:
            raise ValueError("promotion.require_replay must remain true; Lean replay is the retention gate")
        return self


def load_experiment_spec(path: str | Path) -> ExperimentSpec:
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data: Any = json.loads(raw)
    else:
        data = yaml.safe_load(raw)
    if data is None:
        raise ValueError(f"empty experiment spec: {path}")
    return ExperimentSpec.model_validate(data)


def dump_experiment_spec(spec: ExperimentSpec) -> dict[str, Any]:
    """Return a JSON-serializable representation in schema order."""
    return spec.model_dump(mode="json")
