"""Bounded Lean elaborated-proof-size probing.

Counts Expr nodes of a declaration's value (theorem/def/opaque) after metadata
stripping. Used by the proof-shortening orchestrator to compare with/without
proofs of the same proposition.

Fail-closed: any build/parse/timeout/probe failure yields ``verdict='unknown'``
with ``term_size=None``.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional

from solve.lean.replay import build_modules, find_tool


PROOFSIZE_PREFIX = "PROOFSIZE "
PROOFSIZE_DONE = "PROOFSIZE_DONE"


@dataclass(frozen=True)
class ProofSizeResult:
    target: str
    verdict: Literal["ok", "unknown"]
    term_size: Optional[int]
    required_const: Optional[str]
    used_required_const: Optional[bool]
    reason: str


LeanCommandRunner = Callable[[list, Path, int], subprocess.CompletedProcess]


def _run_lake_env_lean(cmd, repo: Path, timeout_seconds: int):
    return subprocess.run(cmd, cwd=repo, text=True, capture_output=True, timeout=timeout_seconds)


def _safe_name_fragment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_")
    if not safe:
        safe = "target"
    if safe[0].isdigit():
        safe = f"t_{safe}"
    return safe[:80]


def parse_proof_size_output(stdout: str) -> ProofSizeResult:
    proof_lines = []
    saw_done = False
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line.startswith(PROOFSIZE_PREFIX):
            proof_lines.append(line[len(PROOFSIZE_PREFIX):])
        elif line == PROOFSIZE_DONE:
            saw_done = True

    if not saw_done:
        raise RuntimeError("proof-size probe did not emit PROOFSIZE_DONE")
    if len(proof_lines) != 1:
        raise RuntimeError(
            f"proof-size probe emitted {len(proof_lines)} PROOFSIZE lines"
        )

    payload = json.loads(proof_lines[0])
    if not isinstance(payload, dict):
        raise RuntimeError("PROOFSIZE payload must be a JSON object")

    target = payload.get("target")
    if not isinstance(target, str):
        raise RuntimeError("PROOFSIZE payload target must be a string")

    verdict = payload.get("verdict")
    if verdict not in ("ok", "unknown"):
        raise RuntimeError(f"PROOFSIZE payload verdict must be 'ok' or 'unknown', got {verdict!r}")

    term_size = payload.get("term_size")
    if term_size is not None and not isinstance(term_size, int):
        raise RuntimeError("PROOFSIZE payload term_size must be int or null")
    # `True`/`False` are ints in Python — reject explicitly.
    if isinstance(term_size, bool):
        raise RuntimeError("PROOFSIZE payload term_size must be int or null")
    if verdict == "ok" and term_size is None:
        raise RuntimeError("PROOFSIZE ok payload must include integer term_size")

    required_const = payload.get("required_const")
    if required_const is not None and not isinstance(required_const, str):
        raise RuntimeError("PROOFSIZE payload required_const must be string or null")

    used_required_const = payload.get("used_required_const")
    if used_required_const is not None and not isinstance(used_required_const, bool):
        raise RuntimeError("PROOFSIZE payload used_required_const must be bool or null")

    reason = payload.get("reason")
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        raise RuntimeError("PROOFSIZE payload reason must be a string")

    return ProofSizeResult(
        target=target,
        verdict=verdict,
        term_size=term_size,
        required_const=required_const,
        used_required_const=used_required_const,
        reason=reason,
    )


def _probe_error(
    target_name: str,
    detail: str,
    required_const: Optional[str],
) -> ProofSizeResult:
    detail = detail.strip() or "unknown failure"
    if len(detail) > 300:
        detail = detail[:300] + "..."
    return ProofSizeResult(
        target=target_name,
        verdict="unknown",
        term_size=None,
        required_const=required_const,
        used_required_const=None,
        reason=f"probe_error: {detail}",
    )


def _wrapper_text(
    *,
    imports,
    heartbeat_budget: int,
    rec_depth: int,
) -> str:
    lines = []
    lines.extend(f"import {imp}" for imp in imports)
    lines.append("import Solve.Tools.ProofSizeProbe")
    lines.append("")
    lines.append(f"set_option maxHeartbeats {heartbeat_budget}")
    lines.append(f"set_option maxRecDepth {rec_depth}")
    lines.append("")
    lines.append("#solve_proof_size_probe")
    lines.append("")
    return "\n".join(lines)


def probe_proof_size(
    target_name: str,
    *,
    repo: Path,
    imports,
    required_const: Optional[str] = None,
    timeout: int = 60,
    heartbeat_budget: int = 20_000,
    rec_depth: int = 1_000,
    runner: LeanCommandRunner = _run_lake_env_lean,
) -> ProofSizeResult:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if heartbeat_budget <= 0:
        raise ValueError("heartbeat_budget must be positive")
    if rec_depth <= 0:
        raise ValueError("rec_depth must be positive")

    imports_list = list(imports)
    required_const_clean = (required_const or "").strip() or None

    repo = Path(repo).resolve()
    try:
        build_modules(repo, [*imports_list, "Solve.Tools.ProofSizeProbe"], timeout=timeout)
    except Exception as exc:
        return _probe_error(target_name, str(exc), required_const_clean)

    generated_dir = repo / "lean" / "Solve" / "Generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    module_path = generated_dir / f"ProofSizeProbe_{_safe_name_fragment(target_name)}.lean"
    module_path.write_text(
        _wrapper_text(
            imports=imports_list,
            heartbeat_budget=heartbeat_budget,
            rec_depth=rec_depth,
        ),
        encoding="utf-8",
    )
    try:
        cmd = [
            find_tool("lake"),
            "env",
            "lean",
            f"-Dweak.solve.proofsize.target={target_name}",
            f"-Dweak.solve.proofsize.requiredConst={required_const_clean or ''}",
            str(module_path),
        ]
        try:
            completed = runner(cmd, repo, timeout)
        except subprocess.TimeoutExpired:
            return _probe_error(target_name, f"timeout after {timeout}s", required_const_clean)
        except Exception as exc:  # pragma: no cover - defensive subprocess boundary
            return _probe_error(target_name, str(exc), required_const_clean)
    finally:
        module_path.unlink(missing_ok=True)

    if completed.returncode != 0:
        return _probe_error(
            target_name,
            (completed.stdout or "") + (completed.stderr or ""),
            required_const_clean,
        )
    try:
        return parse_proof_size_output(completed.stdout or "")
    except Exception as exc:
        return _probe_error(target_name, str(exc), required_const_clean)
