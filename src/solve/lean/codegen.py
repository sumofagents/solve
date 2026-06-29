"""Lean code generation for replayed run-control candidates."""

from __future__ import annotations

from pathlib import Path

from solve.experiments.spec import ExperimentSpec
from solve.verify.candidates import GeneratedCandidate


RUN_CONTROL_NAMESPACE = "Solve.Generated.RunControl"


def _safe_generated_suffix(name: str) -> str:
    suffix = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name).strip("_")
    if not suffix:
        suffix = "spec"
    if suffix[0].isdigit():
        suffix = f"spec_{suffix}"
    return suffix


def _local_decl_name(generated_theorem_name: str) -> str:
    prefix = f"{RUN_CONTROL_NAMESPACE}."
    if generated_theorem_name.startswith(prefix):
        return generated_theorem_name[len(prefix) :]
    return generated_theorem_name.rsplit(".", maxsplit=1)[-1]


def write_run_control_module(
    candidates: list[GeneratedCandidate],
    *,
    repo: Path,
    spec: ExperimentSpec,
    module_suffix: str,
) -> Path:
    safe_suffix = _safe_generated_suffix(module_suffix)
    path = repo / "lean" / "Solve" / "Generated" / f"RunControl_{safe_suffix}.lean"
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.extend(f"import {imp}" for imp in spec.lean.imports)
    lines.append("")
    lines.append("-- Lean requires theorem declarations to carry an explicit type; defs with @parents preserve inferred And.intro types.")
    lines.append(f"namespace {RUN_CONTROL_NAMESPACE}")
    lines.append("")
    for candidate in candidates:
        local_name = _local_decl_name(candidate.generated_theorem_name)
        parent_a, parent_b = candidate.parents
        lines.append(f"def {local_name} := And.intro (@{parent_a}) (@{parent_b})")
        lines.append(f"#check {RUN_CONTROL_NAMESPACE}.{local_name}")
        lines.append(f"#print axioms {RUN_CONTROL_NAMESPACE}.{local_name}")
        lines.append("")
    lines.append(f"end {RUN_CONTROL_NAMESPACE}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
