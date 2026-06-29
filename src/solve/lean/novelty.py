"""Bounded Lean novelty probing against imported theorem environments."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Callable, Literal, NamedTuple

from solve.lean.replay import build_modules, find_tool


NOV_PREFIX = "NOV "
NOV_DONE = "NOV_DONE"
NoveltyVerdict = Literal["existing_defeq_duplicate", "novel_in_imported_env", "unknown"]


class NoveltyProbeResult(NamedTuple):
    classification: NoveltyVerdict
    witness: str | None
    compared: int
    cap_hit: bool
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


def parse_novelty_output(stdout: str) -> NoveltyProbeResult:
    nov_lines: list[str] = []
    saw_done = False
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line.startswith(NOV_PREFIX):
            nov_lines.append(line[len(NOV_PREFIX) :])
        elif line == NOV_DONE:
            saw_done = True

    if not saw_done:
        raise RuntimeError("novelty probe did not emit NOV_DONE")
    if len(nov_lines) != 1:
        raise RuntimeError(f"novelty probe emitted {len(nov_lines)} NOV lines")

    payload = json.loads(nov_lines[0])
    if not isinstance(payload, dict):
        raise RuntimeError("NOV payload must be a JSON object")
    verdict = payload.get("verdict")
    if verdict not in {"existing_defeq_duplicate", "novel_in_imported_env", "unknown"}:
        raise RuntimeError(f"unexpected novelty verdict {verdict!r}")
    compared = payload.get("compared")
    if not isinstance(compared, int):
        raise RuntimeError("NOV payload compared must be an integer")
    cap_hit = payload.get("cap_hit")
    if not isinstance(cap_hit, bool):
        raise RuntimeError("NOV payload cap_hit must be a boolean")
    witness = payload.get("witness")
    if witness is not None and not isinstance(witness, str):
        raise RuntimeError("NOV payload witness must be a string or null")
    return NoveltyProbeResult(
        classification=verdict,
        witness=witness,
        compared=compared,
        cap_hit=cap_hit,
        reason=str(payload.get("reason") or ""),
    )


def _probe_error(detail: str) -> NoveltyProbeResult:
    detail = detail.strip() or "unknown failure"
    if len(detail) > 300:
        detail = detail[:300] + "..."
    return NoveltyProbeResult(
        classification="unknown",
        witness=None,
        compared=0,
        cap_hit=False,
        reason=f"probe_error: {detail}",
    )


def _wrapper_text(
    *,
    imports: list[str],
    heartbeat_budget: int,
    rec_depth: int,
    candidate_cap: int,
) -> str:
    global_heartbeat_budget = max(heartbeat_budget * max(candidate_cap, 1) + 10_000, heartbeat_budget)
    lines: list[str] = []
    lines.extend(f"import {imp}" for imp in imports)
    lines.append("import Solve.Tools.NoveltyProbe")
    lines.append("")
    lines.append(f"set_option maxHeartbeats {global_heartbeat_budget}")
    lines.append(f"set_option maxRecDepth {rec_depth}")
    lines.append("")
    lines.append("#solve_novelty_probe")
    lines.append("")
    return "\n".join(lines)


def probe_novelty(
    target_name: str,
    *,
    repo: Path,
    imports: list[str],
    prefixes: list[str],
    candidate_cap: int,
    timeout: int,
    heartbeat_budget: int = 20_000,
    rec_depth: int = 1_000,
    runner: LeanCommandRunner = _run_lake_env_lean,
) -> NoveltyProbeResult:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if candidate_cap < 0:
        raise ValueError("candidate_cap must be non-negative")
    if heartbeat_budget <= 0:
        raise ValueError("heartbeat_budget must be positive")
    if rec_depth <= 0:
        raise ValueError("rec_depth must be positive")

    repo = repo.resolve()
    build_modules(repo, imports, timeout=timeout)
    generated_dir = repo / "lean" / "Solve" / "Generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    module_path = generated_dir / f"NoveltyProbe_{_safe_name_fragment(target_name)}.lean"
    module_path.write_text(
        _wrapper_text(
            imports=imports,
            heartbeat_budget=heartbeat_budget,
            rec_depth=rec_depth,
            candidate_cap=candidate_cap,
        ),
        encoding="utf-8",
    )
    cmd = [
        find_tool("lake"),
        "env",
        "lean",
        f"-Dweak.solve.novelty.target={target_name}",
        f"-Dweak.solve.novelty.prefixes={','.join(prefixes)}",
        f"-Dweak.solve.novelty.candidateCap={candidate_cap}",
        f"-Dweak.solve.novelty.heartbeatBudget={heartbeat_budget}",
        str(module_path),
    ]
    try:
        completed = runner(cmd, repo, timeout)
    except subprocess.TimeoutExpired:
        return _probe_error(f"timeout after {timeout}s")
    except Exception as exc:  # pragma: no cover - defensive subprocess boundary
        return _probe_error(str(exc))
    finally:
        module_path.unlink(missing_ok=True)

    if completed.returncode != 0:
        return _probe_error((completed.stdout or "") + (completed.stderr or ""))
    try:
        return parse_novelty_output(completed.stdout or "")
    except Exception as exc:
        return _probe_error(str(exc))
