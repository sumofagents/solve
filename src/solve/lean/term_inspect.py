"""Bounded Lean term inspection for structural packaging detection."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from solve.lean.replay import build_modules, find_tool


STRUCT_PREFIX = "STRUCT "
STRUCT_DONE = "STRUCT_DONE"


@dataclass(frozen=True)
class StructuralArgument:
    kind: Literal["const", "fvar", "literal", "other"]
    name: str | None
    imported: bool | None


@dataclass(frozen=True)
class StructuralProbeResult:
    target: str
    head: str | None
    args: tuple[StructuralArgument, ...]
    verdict: Literal["structural", "non_structural", "error"]
    reason: str

    @property
    def structural_packaging(self) -> bool:
        return self.verdict == "structural"


LeanCommandRunner = Callable[[list[str], Path, int], subprocess.CompletedProcess[str]]


def _run_lake_env_lean(cmd: list[str], repo: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=repo, text=True, capture_output=True, timeout=timeout_seconds)


def _safe_name_fragment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_")
    if not safe:
        safe = "target"
    if safe[0].isdigit():
        safe = f"t_{safe}"
    return safe[:80]


def parse_structural_output(stdout: str) -> StructuralProbeResult:
    struct_lines: list[str] = []
    saw_done = False
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line.startswith(STRUCT_PREFIX):
            struct_lines.append(line[len(STRUCT_PREFIX) :])
        elif line == STRUCT_DONE:
            saw_done = True

    if not saw_done:
        raise RuntimeError("structural probe did not emit STRUCT_DONE")
    if len(struct_lines) != 1:
        raise RuntimeError(f"structural probe emitted {len(struct_lines)} STRUCT lines")

    payload = json.loads(struct_lines[0])
    if not isinstance(payload, dict):
        raise RuntimeError("STRUCT payload must be a JSON object")
    args_raw = payload.get("args")
    if not isinstance(args_raw, list):
        raise RuntimeError("STRUCT payload args must be an array")

    args: list[StructuralArgument] = []
    for arg in args_raw:
        if not isinstance(arg, dict):
            raise RuntimeError("STRUCT argument must be a JSON object")
        args.append(
            StructuralArgument(
                kind=arg.get("kind"),
                name=arg.get("name"),
                imported=arg.get("imported"),
            )
        )

    return StructuralProbeResult(
        target=str(payload.get("target") or ""),
        head=payload.get("head"),
        args=tuple(args),
        verdict=payload.get("verdict"),
        reason=str(payload.get("reason") or ""),
    )


def _probe_error(target_name: str, detail: str) -> StructuralProbeResult:
    detail = detail.strip() or "unknown failure"
    if len(detail) > 300:
        detail = detail[:300] + "..."
    return StructuralProbeResult(
        target=target_name,
        head=None,
        args=(),
        verdict="error",
        reason=f"probe_error: {detail}",
    )


def _wrapper_text(
    *,
    target_name: str,
    imports: list[str],
    heartbeat_budget: int,
    rec_depth: int,
) -> str:
    lines: list[str] = []
    lines.extend(f"import {imp}" for imp in imports)
    lines.append("import Solve.Tools.TermProbe")
    lines.append("")
    lines.append(f"set_option maxHeartbeats {heartbeat_budget}")
    lines.append(f"set_option maxRecDepth {rec_depth}")
    lines.append("")
    lines.append(f"#solve_structural_probe {target_name}")
    lines.append("")
    return "\n".join(lines)


def probe_structural_packaging_details(
    target_name: str,
    *,
    repo: Path,
    imports: list[str],
    timeout: int,
    heartbeat_budget: int = 20_000,
    rec_depth: int = 1_000,
    runner: LeanCommandRunner = _run_lake_env_lean,
) -> StructuralProbeResult:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if heartbeat_budget <= 0:
        raise ValueError("heartbeat_budget must be positive")
    if rec_depth <= 0:
        raise ValueError("rec_depth must be positive")

    repo = repo.resolve()
    build_modules(repo, imports, timeout=timeout)
    generated_dir = repo / "lean" / "Solve" / "Generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    module_path = generated_dir / f"StructProbe_{_safe_name_fragment(target_name)}.lean"
    module_path.write_text(
        _wrapper_text(
            target_name=target_name,
            imports=imports,
            heartbeat_budget=heartbeat_budget,
            rec_depth=rec_depth,
        ),
        encoding="utf-8",
    )
    cmd = [
        find_tool("lake"),
        "env",
        "lean",
        f"-Dweak.solve.probe.target={target_name}",
        str(module_path),
    ]
    try:
        completed = runner(cmd, repo, timeout)
    except subprocess.TimeoutExpired:
        return _probe_error(target_name, f"timeout after {timeout}s")
    except Exception as exc:  # pragma: no cover - defensive subprocess boundary
        return _probe_error(target_name, str(exc))
    finally:
        module_path.unlink(missing_ok=True)

    if completed.returncode != 0:
        return _probe_error(target_name, (completed.stdout or "") + (completed.stderr or ""))
    try:
        return parse_structural_output(completed.stdout or "")
    except Exception as exc:
        return _probe_error(target_name, str(exc))


def probe_structural_packaging(
    target_name: str,
    *,
    repo: Path,
    imports: list[str],
    timeout: int,
    heartbeat_budget: int = 20_000,
    rec_depth: int = 1_000,
    runner: LeanCommandRunner = _run_lake_env_lean,
) -> tuple[bool, str]:
    result = probe_structural_packaging_details(
        target_name,
        repo=repo,
        imports=imports,
        timeout=timeout,
        heartbeat_budget=heartbeat_budget,
        rec_depth=rec_depth,
        runner=runner,
    )
    return result.structural_packaging, result.reason
