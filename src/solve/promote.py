"""Promotion pipeline for replay-verified atoms."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from solve.experiments.spec import ExperimentSpec, load_experiment_spec
from solve.lean.promote_codegen import (
    promoted_module_name,
    source_run_control_module_name,
    write_promoted_module,
)
from solve.lean.replay import build_modules, replay_file
from solve.verify.promoted import (
    PromotedAtomRecord,
    PromotionMetrics,
    write_promoted_jsonl,
    write_promotion_metrics,
)
from solve.verify.receipts import ReplayResult


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve_spec_path(spec_path: str | Path, repo: Path) -> Path:
    path = Path(spec_path)
    if path.is_absolute() or path.exists():
        return path
    return repo / path


def _read_jsonl_dicts(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"classified JSONL line {line_no} must be an object")
            rows.append(payload)
    return rows


def _validate_classified_integrity(rows: list[dict[str, Any]], spec: ExperimentSpec) -> None:
    for index, row in enumerate(rows, start=1):
        if row.get("experiment_id") != spec.name:
            raise ValueError(
                f"classified row {index} experiment_id {row.get('experiment_id')!r} != spec name {spec.name!r}"
            )
        if row.get("toolchain") != spec.lean.toolchain:
            raise ValueError(
                f"classified row {index} toolchain {row.get('toolchain')!r} != spec toolchain {spec.lean.toolchain!r}"
            )
        if list(row.get("imports") or []) != list(spec.lean.imports):
            raise ValueError(
                f"classified row {index} imports {row.get('imports')!r} != spec imports {spec.lean.imports!r}"
            )


def _require_str(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"classified promotable row missing non-empty string field {key!r}")
    return value


def _sanitize_local_name(source_generated_theorem_name: str) -> str:
    base = source_generated_theorem_name.rsplit(".", maxsplit=1)[-1]
    local = re.sub(r"[^A-Za-z0-9_]", "_", base).strip("_")
    if not local:
        local = "promoted_atom"
    if local[0].isdigit():
        local = f"p_{local}"
    return local


def _dedupe_local_names(source_names: list[str]) -> list[str]:
    used: set[str] = set()
    out: list[str] = []
    for source_name in source_names:
        base = _sanitize_local_name(source_name)
        local = base
        suffix = 2
        while local in used:
            local = f"{base}_{suffix}"
            suffix += 1
        used.add(local)
        out.append(local)
    return out


def make_promoted_record_id(source_record_id: str, local_name: str) -> str:
    return hashlib.sha256(f"{source_record_id}{local_name}".encode("utf-8")).hexdigest()[:16]


def _replay_result_from_completed(result: subprocess.CompletedProcess[str]) -> ReplayResult:
    args = result.args
    if isinstance(args, list):
        command = [str(part) for part in args]
    elif isinstance(args, tuple):
        command = [str(part) for part in args]
    else:
        command = [str(args)]
    return ReplayResult(
        command=command,
        exit_code=int(result.returncode),
        stdout=result.stdout or "",
        stderr=result.stderr or "",
    )


def _atomic_write_promoted_jsonl(path: Path, records: list[PromotedAtomRecord]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        write_promoted_jsonl(tmp, records)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def _write_metrics_if_requested(path: Path | None, metrics: PromotionMetrics) -> None:
    if path is not None:
        write_promotion_metrics(path, metrics)


def _metrics(
    *,
    spec: ExperimentSpec,
    promoted_count: int,
    skipped_not_promotable_count: int,
    rejected_replay_failure: bool,
    promoted_module: str | None,
    started_at_iso: str | None,
    finished_at_iso: str | None,
    start: float,
    out_promoted: Path,
) -> PromotionMetrics:
    return PromotionMetrics(
        experiment_id=spec.name,
        toolchain=spec.lean.toolchain,
        promoted_count=promoted_count,
        skipped_not_promotable_count=skipped_not_promotable_count,
        rejected_replay_failure=rejected_replay_failure,
        promoted_module=promoted_module,
        started_at_iso=started_at_iso,
        finished_at_iso=finished_at_iso,
        duration_seconds=max(0.0, time.monotonic() - start),
        out_promoted=str(out_promoted),
    )


def promote(
    spec_path: str | Path,
    *,
    repo: Path,
    classified_path: Path,
    out_promoted: Path,
    metrics_path: Path | None,
    timeout: int = 600,
) -> PromotionMetrics:
    repo = repo.resolve()
    started_at_iso = _utc_now_iso()
    start = time.monotonic()
    spec = load_experiment_spec(_resolve_spec_path(spec_path, repo))
    rows = _read_jsonl_dicts(classified_path)
    _validate_classified_integrity(rows, spec)

    promotable_rows = [row for row in rows if row.get("promotable") is True]
    skipped_not_promotable_count = len(rows) - len(promotable_rows)
    out_promoted = Path(out_promoted)
    if not out_promoted.is_absolute():
        out_promoted = repo / out_promoted
    if metrics_path is not None and not metrics_path.is_absolute():
        metrics_path = repo / metrics_path

    if not promotable_rows:
        write_promoted_jsonl(out_promoted, [])
        finished_at_iso = _utc_now_iso()
        metrics = _metrics(
            spec=spec,
            promoted_count=0,
            skipped_not_promotable_count=skipped_not_promotable_count,
            rejected_replay_failure=False,
            promoted_module=None,
            started_at_iso=started_at_iso,
            finished_at_iso=finished_at_iso,
            start=start,
            out_promoted=out_promoted,
        )
        _write_metrics_if_requested(metrics_path, metrics)
        return metrics

    module_name = promoted_module_name(spec)
    source_module = source_run_control_module_name(spec)
    promoted_at_iso = _utc_now_iso()
    source_names = [_require_str(row, "generated_theorem_name") for row in promotable_rows]
    local_names = _dedupe_local_names(source_names)
    records: list[PromotedAtomRecord] = []
    for row, local_name in zip(promotable_rows, local_names):
        fully_qualified_name = f"{module_name}.{local_name}"
        source_record_id = _require_str(row, "record_id")
        records.append(
            PromotedAtomRecord(
                record_id=make_promoted_record_id(source_record_id, local_name),
                experiment_id=spec.name,
                toolchain=spec.lean.toolchain,
                imports=list(spec.lean.imports),
                source_module=source_module,
                source_record_id=source_record_id,
                source_generated_theorem_name=_require_str(row, "generated_theorem_name"),
                statement=_require_str(row, "statement"),
                proof_term=_require_str(row, "proof_term"),
                promoted_module=module_name,
                local_name=local_name,
                fully_qualified_name=fully_qualified_name,
                promoted_at_iso=promoted_at_iso,
            )
        )

    module_path = write_promoted_module(records, repo=repo, spec=spec)
    # Compile the promoted module into the lake build graph so later epoch-1
    # modules can import it by name. This also serves as the replay gate.
    try:
        build_modules(repo, [module_name], timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        module_path.unlink(missing_ok=True)
        out_promoted.unlink(missing_ok=True)
        finished_at_iso = _utc_now_iso()
        metrics = _metrics(
            spec=spec,
            promoted_count=0,
            skipped_not_promotable_count=skipped_not_promotable_count,
            rejected_replay_failure=True,
            promoted_module=None,
            started_at_iso=started_at_iso,
            finished_at_iso=finished_at_iso,
            start=start,
            out_promoted=out_promoted,
        )
        _write_metrics_if_requested(metrics_path, metrics)
        raise RuntimeError(f"promoted module build timed out after {exc.timeout}s") from exc
    except RuntimeError as exc:
        module_path.unlink(missing_ok=True)
        out_promoted.unlink(missing_ok=True)
        finished_at_iso = _utc_now_iso()
        metrics = _metrics(
            spec=spec,
            promoted_count=0,
            skipped_not_promotable_count=skipped_not_promotable_count,
            rejected_replay_failure=True,
            promoted_module=None,
            started_at_iso=started_at_iso,
            finished_at_iso=finished_at_iso,
            start=start,
            out_promoted=out_promoted,
        )
        _write_metrics_if_requested(metrics_path, metrics)
        raise RuntimeError(f"promoted module build failed: {exc}") from exc
    try:
        replay = _replay_result_from_completed(replay_file(module_path, cwd=repo, timeout=timeout))
    except subprocess.TimeoutExpired as exc:
        module_path.unlink(missing_ok=True)
        out_promoted.unlink(missing_ok=True)
        finished_at_iso = _utc_now_iso()
        metrics = _metrics(
            spec=spec,
            promoted_count=0,
            skipped_not_promotable_count=skipped_not_promotable_count,
            rejected_replay_failure=True,
            promoted_module=None,
            started_at_iso=started_at_iso,
            finished_at_iso=finished_at_iso,
            start=start,
            out_promoted=out_promoted,
        )
        _write_metrics_if_requested(metrics_path, metrics)
        raise RuntimeError(f"promoted module replay timed out after {exc.timeout}s") from exc

    if not replay.accepted:
        module_path.unlink(missing_ok=True)
        out_promoted.unlink(missing_ok=True)
        finished_at_iso = _utc_now_iso()
        metrics = _metrics(
            spec=spec,
            promoted_count=0,
            skipped_not_promotable_count=skipped_not_promotable_count,
            rejected_replay_failure=True,
            promoted_module=None,
            started_at_iso=started_at_iso,
            finished_at_iso=finished_at_iso,
            start=start,
            out_promoted=out_promoted,
        )
        _write_metrics_if_requested(metrics_path, metrics)
        detail = (replay.stdout + replay.stderr).strip()
        raise RuntimeError(f"promoted module replay failed: {detail}")

    _atomic_write_promoted_jsonl(out_promoted, records)
    finished_at_iso = _utc_now_iso()
    metrics = _metrics(
        spec=spec,
        promoted_count=len(records),
        skipped_not_promotable_count=skipped_not_promotable_count,
        rejected_replay_failure=False,
        promoted_module=module_name,
        started_at_iso=started_at_iso,
        finished_at_iso=finished_at_iso,
        start=start,
        out_promoted=out_promoted,
    )
    _write_metrics_if_requested(metrics_path, metrics)
    return metrics
