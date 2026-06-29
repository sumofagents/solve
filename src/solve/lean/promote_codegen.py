"""Lean code generation for replay-verified promoted atom modules."""

from __future__ import annotations

import re
from pathlib import Path

from solve.experiments.spec import ExperimentSpec
from solve.verify.promoted import PromotedAtomRecord


def _safe_generated_suffix(name: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_")
    if not suffix:
        suffix = "spec"
    if suffix[0].isdigit():
        suffix = f"spec_{suffix}"
    return suffix


def promoted_module_name(spec: ExperimentSpec) -> str:
    return f"Solve.Generated.Promoted_{_safe_generated_suffix(spec.name)}"


def source_run_control_module_name(spec: ExperimentSpec) -> str:
    return f"Solve.Generated.RunControl_{_safe_generated_suffix(spec.name)}"


def write_promoted_module(
    records: list[PromotedAtomRecord],
    *,
    repo: Path,
    spec: ExperimentSpec,
) -> Path:
    safe_suffix = _safe_generated_suffix(spec.name)
    path = repo / "lean" / "Solve" / "Generated" / f"Promoted_{safe_suffix}.lean"
    if not records:
        return path

    module = promoted_module_name(spec)
    source_module = source_run_control_module_name(spec)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.extend(f"import {imp}" for imp in spec.lean.imports)
    lines.append(f"import {source_module}")
    lines.append("")
    lines.append(f"namespace {module}")
    lines.append("")
    for record in records:
        lines.append(f"def {record.local_name} := {record.proof_term}")
        lines.append(f"#check {module}.{record.local_name}")
        lines.append(f"#print axioms {module}.{record.local_name}")
        lines.append("")
    lines.append(f"end {module}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
