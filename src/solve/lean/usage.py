"""Bounded Lean proof-term usage probing for promoted constants."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from solve.lean.replay import build_modules, find_tool


USAGE_PREFIX = "USAGE "
USAGE_DONE = "USAGE_DONE"


@dataclass(frozen=True)
class UsageProbeResult:
    target: str
    used_promoted: tuple[str, ...]
    unknown: bool
    reason: str


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


def parse_usage_output(stdout: str) -> UsageProbeResult:
    usage_lines: list[str] = []
    saw_done = False
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line.startswith(USAGE_PREFIX):
            usage_lines.append(line[len(USAGE_PREFIX) :])
        elif line == USAGE_DONE:
            saw_done = True

    if not saw_done:
        raise RuntimeError("usage probe did not emit USAGE_DONE")
    if len(usage_lines) != 1:
        raise RuntimeError(f"usage probe emitted {len(usage_lines)} USAGE lines")

    payload = json.loads(usage_lines[0])
    if not isinstance(payload, dict):
        raise RuntimeError("USAGE payload must be a JSON object")
    target = payload.get("target")
    if not isinstance(target, str):
        raise RuntimeError("USAGE payload target must be a string")
    used_raw = payload.get("used_promoted")
    if not isinstance(used_raw, list):
        raise RuntimeError("USAGE payload used_promoted must be an array")
    used: list[str] = []
    for item in used_raw:
        if not isinstance(item, str):
            raise RuntimeError("USAGE payload used_promoted entries must be strings")
        used.append(item)
    unknown = payload.get("unknown")
    if not isinstance(unknown, bool):
        raise RuntimeError("USAGE payload unknown must be a boolean")

    return UsageProbeResult(
        target=target,
        used_promoted=tuple(used),
        unknown=unknown,
        reason=str(payload.get("reason") or ""),
    )


def _probe_error(target_name: str, detail: str) -> UsageProbeResult:
    detail = detail.strip() or "unknown failure"
    if len(detail) > 300:
        detail = detail[:300] + "..."
    return UsageProbeResult(
        target=target_name,
        used_promoted=(),
        unknown=True,
        reason=f"probe_error: {detail}",
    )


def _wrapper_text(
    *,
    imports: list[str],
    heartbeat_budget: int,
    rec_depth: int,
) -> str:
    lines: list[str] = []
    lines.extend(f"import {imp}" for imp in imports)
    lines.append("import Solve.Tools.UsageProbe")
    lines.append("")
    lines.append(f"set_option maxHeartbeats {heartbeat_budget}")
    lines.append(f"set_option maxRecDepth {rec_depth}")
    lines.append("")
    lines.append("#solve_usage_probe")
    lines.append("")
    return "\n".join(lines)


def probe_usage(
    target_name: str,
    *,
    repo: Path,
    imports: list[str],
    promoted_names: list[str],
    timeout: int,
    heartbeat_budget: int = 20_000,
    rec_depth: int = 1_000,
    max_constants: int = 10_000,
    runner: LeanCommandRunner = _run_lake_env_lean,
) -> UsageProbeResult:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if heartbeat_budget <= 0:
        raise ValueError("heartbeat_budget must be positive")
    if rec_depth <= 0:
        raise ValueError("rec_depth must be positive")
    if max_constants <= 0:
        raise ValueError("max_constants must be positive")

    repo = repo.resolve()
    try:
        build_modules(repo, [*imports, "Solve.Tools.UsageProbe"], timeout=timeout)
    except Exception as exc:
        # Probe failure -> False/unknown, never True.
        return _probe_error(target_name, str(exc))

    generated_dir = repo / "lean" / "Solve" / "Generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    module_path = generated_dir / f"UsageProbe_{_safe_name_fragment(target_name)}.lean"
    module_path.write_text(
        _wrapper_text(
            imports=imports,
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
            f"-Dweak.solve.usage.target={target_name}",
            f"-Dweak.solve.usage.promoted={','.join(promoted_names)}",
            f"-Dweak.solve.usage.maxConstants={max_constants}",
            str(module_path),
        ]
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
        return parse_usage_output(completed.stdout or "")
    except Exception as exc:
        return _probe_error(target_name, str(exc))
