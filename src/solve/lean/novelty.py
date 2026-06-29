"""Bounded Lean novelty probing against imported theorem environments."""

from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path
from typing import Callable, Literal, NamedTuple

from solve.lean.replay import build_modules, find_tool


NOV_PREFIX = "NOV "
NOV_INDEX_PREFIX = "NOV_INDEX "
NOV_DONE = "NOV_DONE"
NoveltyVerdict = Literal["existing_defeq_duplicate", "novel_in_imported_env", "unknown"]
NoveltyScope = Literal["imported", "global"]
NoveltyVerifyMode = Literal["discrtree", "brute"]


class NoveltyProbeResult(NamedTuple):
    classification: NoveltyVerdict
    witness: str | None
    compared: int
    cap_hit: bool
    reason: str


LeanCommandRunner = Callable[[list[str], Path, int], subprocess.CompletedProcess[str]]


def _run_lake_env_lean(cmd: list[str], repo: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=repo, text=True, capture_output=True, timeout=timeout_seconds)


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


def _result_from_payload(payload: object) -> tuple[str, NoveltyProbeResult]:
    if not isinstance(payload, dict):
        raise RuntimeError("NOV payload must be a JSON object")
    target = payload.get("target")
    if not isinstance(target, str) or not target:
        raise RuntimeError("NOV payload target must be a non-empty string")
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
    return target, NoveltyProbeResult(
        classification=verdict,
        witness=witness,
        compared=compared,
        cap_hit=cap_hit,
        reason=str(payload.get("reason") or ""),
    )


def parse_novelty_batch_output(stdout: str, targets: list[str]) -> dict[str, NoveltyProbeResult]:
    results: dict[str, NoveltyProbeResult] = {}
    saw_done = False
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line.startswith(NOV_PREFIX):
            target, result = _result_from_payload(json.loads(line[len(NOV_PREFIX) :]))
            if target in results:
                raise RuntimeError(f"duplicate NOV payload for target {target}")
            results[target] = result
        elif line.startswith(NOV_INDEX_PREFIX):
            json.loads(line[len(NOV_INDEX_PREFIX) :])
        elif line == NOV_DONE:
            saw_done = True

    if not saw_done:
        raise RuntimeError("novelty probe did not emit NOV_DONE")

    requested = set(targets)
    extra = sorted(set(results) - requested)
    if extra:
        raise RuntimeError(f"novelty probe emitted unexpected targets: {', '.join(extra[:5])}")
    for target in targets:
        if target not in results:
            results[target] = _probe_error(f"missing NOV result for target {target}")
    return results


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


def _merge_prefixes(prefixes: list[str], promoted_prefixes: list[str] | None) -> list[str]:
    merged: list[str] = []
    for prefix in [*prefixes, *(promoted_prefixes or [])]:
        if prefix and prefix not in merged:
            merged.append(prefix)
    return merged


def _wrapper_text(
    *,
    imports: list[str],
    scope: NoveltyScope,
    heartbeat_budget: int,
    rec_depth: int,
    candidate_cap: int,
    target_count: int,
) -> str:
    global_heartbeat_budget = max(
        heartbeat_budget * max(candidate_cap, 1) * max(target_count, 1) + 10_000,
        heartbeat_budget,
    )
    wrapper_imports = list(imports)
    if scope == "global" and "Mathlib" not in wrapper_imports:
        wrapper_imports.append("Mathlib")
    lines: list[str] = []
    lines.extend(f"import {imp}" for imp in wrapper_imports)
    lines.append("import Solve.Tools.NoveltyProbe")
    lines.append("")
    lines.append(f"set_option maxHeartbeats {global_heartbeat_budget}")
    lines.append(f"set_option maxRecDepth {rec_depth}")
    lines.append("")
    lines.append("#solve_novelty_probe")
    lines.append("")
    return "\n".join(lines)


def _batch_file_stem(targets: list[str], imports: list[str], scope: str, verify_mode: str) -> str:
    digest = hashlib.sha256()
    for value in [*targets, "--imports--", *imports, "--scope--", scope, "--mode--", verify_mode]:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def probe_novelty_batch(
    targets: list[str],
    *,
    repo: Path,
    imports: list[str],
    prefixes: list[str],
    scope: NoveltyScope = "imported",
    verify_mode: NoveltyVerifyMode = "discrtree",
    promoted_prefixes: list[str] | None = None,
    candidate_cap: int,
    timeout: int,
    heartbeat_budget: int = 20_000,
    rec_depth: int = 1_000,
    runner: LeanCommandRunner = _run_lake_env_lean,
) -> dict[str, NoveltyProbeResult]:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if candidate_cap < 0:
        raise ValueError("candidate_cap must be non-negative")
    if heartbeat_budget <= 0:
        raise ValueError("heartbeat_budget must be positive")
    if rec_depth <= 0:
        raise ValueError("rec_depth must be positive")
    if scope not in {"imported", "global"}:
        raise ValueError("scope must be 'imported' or 'global'")
    if verify_mode not in {"discrtree", "brute"}:
        raise ValueError("verify_mode must be 'discrtree' or 'brute'")

    unique_targets = list(dict.fromkeys(targets))
    if not unique_targets:
        return {}

    repo = repo.resolve()
    all_prefixes = _merge_prefixes(prefixes, promoted_prefixes)
    wrapper_imports = list(imports)
    if scope == "global" and "Mathlib" not in wrapper_imports:
        wrapper_imports.append("Mathlib")
    build_modules(repo, [*wrapper_imports, "Solve.Tools.NoveltyProbe"], timeout=timeout)
    generated_dir = repo / "lean" / "Solve" / "Generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    stem = _batch_file_stem(unique_targets, imports, scope, verify_mode)
    targets_path = generated_dir / f"NoveltyTargets_{stem}.jsonl"
    module_path = generated_dir / f"NoveltyProbe_{stem}.lean"
    targets_path.write_text(
        "".join(json.dumps({"name": target}, sort_keys=True) + "\n" for target in unique_targets),
        encoding="utf-8",
    )
    module_path.write_text(
        _wrapper_text(
            imports=imports,
            scope=scope,
            heartbeat_budget=heartbeat_budget,
            rec_depth=rec_depth,
            candidate_cap=candidate_cap,
            target_count=len(unique_targets),
        ),
        encoding="utf-8",
    )
    cmd = [
        find_tool("lake"),
        "env",
        "lean",
        f"-Dweak.solve.novelty.targetsFile={targets_path}",
        f"-Dweak.solve.novelty.prefixes={','.join(all_prefixes)}",
        f"-Dweak.solve.novelty.verifyMode={verify_mode}",
        f"-Dweak.solve.novelty.globalScope={'true' if scope == 'global' else 'false'}",
        f"-Dweak.solve.novelty.candidateCap={candidate_cap}",
        f"-Dweak.solve.novelty.heartbeatBudget={heartbeat_budget}",
        str(module_path),
    ]
    try:
        completed = runner(cmd, repo, timeout)
    except subprocess.TimeoutExpired:
        return {target: _probe_error(f"timeout after {timeout}s") for target in unique_targets}
    except Exception as exc:  # pragma: no cover - defensive subprocess boundary
        return {target: _probe_error(str(exc)) for target in unique_targets}
    finally:
        targets_path.unlink(missing_ok=True)
        module_path.unlink(missing_ok=True)

    if completed.returncode != 0:
        detail = (completed.stdout or "") + (completed.stderr or "")
        return {target: _probe_error(detail) for target in unique_targets}
    try:
        return parse_novelty_batch_output(completed.stdout or "", unique_targets)
    except Exception as exc:
        return {target: _probe_error(str(exc)) for target in unique_targets}


def probe_novelty(
    target_name: str,
    *,
    repo: Path,
    imports: list[str],
    prefixes: list[str],
    promoted_prefixes: list[str] | None = None,
    scope: NoveltyScope = "imported",
    verify_mode: NoveltyVerifyMode = "discrtree",
    candidate_cap: int,
    timeout: int,
    heartbeat_budget: int = 20_000,
    rec_depth: int = 1_000,
    runner: LeanCommandRunner = _run_lake_env_lean,
) -> NoveltyProbeResult:
    return probe_novelty_batch(
        [target_name],
        repo=repo,
        imports=imports,
        prefixes=prefixes,
        scope=scope,
        verify_mode=verify_mode,
        promoted_prefixes=promoted_prefixes,
        candidate_cap=candidate_cap,
        timeout=timeout,
        heartbeat_budget=heartbeat_budget,
        rec_depth=rec_depth,
        runner=runner,
    )[target_name]
