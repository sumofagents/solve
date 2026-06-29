"""Lean-environment seed atom enumeration.

This module is core verifier plumbing. It shells out to Lean and parses only the
machine-readable atom lines emitted by ``Solve.Tools.AtomDump``.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from solve.experiments.spec import ExperimentSpec
from solve.lean.replay import find_tool


ATOM_PREFIX = "ATOM "
ATOM_DONE_PREFIX = "ATOM_DONE count="


class AtomRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(..., min_length=1)
    kind: Literal["def", "theorem", "axiom", "ctor", "inductive", "opaque", "quot", "other"]
    type_pp: str = Field(..., min_length=1)
    type_hash: str = Field(..., min_length=1)
    binder_count: int | None
    arity: int | None
    module: str | None
    axioms: list[str] | None

    @field_validator("axioms", mode="before")
    @classmethod
    def reject_unknown_axioms_marker(cls, value: Any) -> Any:
        if value == "unknown":
            raise ValueError("axioms must be null or an explicit array, not 'unknown'")
        return value


def parse_atom_line(line: str) -> AtomRecord:
    if not line.startswith(ATOM_PREFIX):
        raise ValueError("atom line must start with 'ATOM '")
    payload = json.loads(line[len(ATOM_PREFIX) :])
    if not isinstance(payload, dict):
        raise ValueError("ATOM payload must be a JSON object")
    if "axioms" not in payload:
        raise ValueError("ATOM payload must include axioms as null or an explicit array")
    if payload["axioms"] is not None and not isinstance(payload["axioms"], list):
        raise ValueError("axioms must be null or an explicit array")
    return AtomRecord.model_validate(payload)


def _safe_module_suffix(name: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9_]", "_", name)
    suffix = suffix.strip("_") or "spec"
    if suffix[0].isdigit():
        suffix = f"spec_{suffix}"
    return suffix


def _write_wrapper(spec: ExperimentSpec, repo: Path) -> Path:
    generated = repo / "lean" / "Solve" / "Generated"
    generated.mkdir(parents=True, exist_ok=True)
    path = generated / f"AtomDump_{_safe_module_suffix(spec.name)}.lean"
    imports = "\n".join(["import Solve.Tools.AtomDump", *[f"import {imp}" for imp in spec.lean.imports]])
    path.write_text(f"{imports}\n\n#solve_atom_dump\n", encoding="utf-8")
    return path


def _run_atom_dump(
    wrapper: Path,
    *,
    repo: Path,
    prefixes: list[str],
    seed_limit: int,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        find_tool("lake"),
        "env",
        "lean",
        f"-Dweak.solve.atom.prefixes={','.join(prefixes)}",
        f"-Dweak.solve.atom.seedLimit={seed_limit}",
        str(wrapper),
    ]
    return subprocess.run(cmd, cwd=repo, text=True, capture_output=True, timeout=timeout)


def _build_atom_tool(*, repo: Path, timeout: int) -> None:
    result = subprocess.run(
        [find_tool("lake"), "build", "Solve.Tools.AtomDump"],
        cwd=repo,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)


def enumerate_atoms(spec: ExperimentSpec, *, repo: Path, timeout: int) -> list[AtomRecord]:
    repo = repo.resolve()
    _build_atom_tool(repo=repo, timeout=timeout)
    wrapper = _write_wrapper(spec, repo)
    result = _run_atom_dump(
        wrapper,
        repo=repo,
        prefixes=spec.corpus.namespace_prefixes,
        seed_limit=spec.corpus.seed_limit,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)

    records: list[AtomRecord] = []
    done_count: int | None = None
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if line.startswith(ATOM_PREFIX):
            records.append(parse_atom_line(line))
        elif line.startswith(ATOM_DONE_PREFIX):
            done_count = int(line[len(ATOM_DONE_PREFIX) :])

    if done_count is None:
        raise RuntimeError("atom dump did not emit ATOM_DONE")
    if done_count != len(records):
        raise RuntimeError(f"ATOM_DONE count={done_count} did not match parsed records={len(records)}")
    wrapper.unlink(missing_ok=True)
    return records
