"""Bounded Lean automation classifier for retained receipts."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pydantic import Field

from solve.experiments.spec import ExperimentSpec, load_experiment_spec
from solve.lean.replay import find_tool
from solve.verify.candidates import StrictFrozenModel
from solve.verify.receipts import AutomationClassification, CandidateReceipt


TACTIC_BOUQUET = ("simp", "decide", "omega", "tauto", "simp?", "exact?")
TRIVIAL_BY_AUTOMATION: AutomationClassification = "trivial_by_automation"
NOT_TRIVIAL_UNDER_BOUND: AutomationClassification = "not_trivial_under_bound"
AUTOMATION_ERROR: AutomationClassification = "automation_error"


@dataclass(frozen=True)
class AutomationBounds:
    heartbeat_budget: int = 20_000
    step_budget: int = 1_000
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        if self.heartbeat_budget <= 0:
            raise ValueError("heartbeat_budget must be positive")
        if self.step_budget <= 0:
            raise ValueError("step_budget must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True)
class AttemptResult:
    tactic: str
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    runner_error: str | None = None

    @property
    def closed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and self.runner_error is None

    @property
    def infrastructure_error(self) -> bool:
        return self.timed_out or self.runner_error is not None


class ClassificationMetrics(StrictFrozenModel):
    experiment_id: str = Field(..., min_length=1)
    toolchain: str = Field(..., min_length=1)
    imports: list[str]
    total_receipts_read: int = Field(..., ge=0)
    retained_receipts_classified: int = Field(..., ge=0)
    skipped_not_retained_count: int = Field(..., ge=0)
    cap_skipped_count: int = Field(..., ge=0)
    counts_by_automation_classification: dict[str, int]
    counts_by_automation_closed_by: dict[str, int]
    automation_attempted: list[str]
    automation_heartbeat_budget: int = Field(..., gt=0)
    automation_step_budget: int = Field(..., gt=0)
    automation_timeout_seconds: int = Field(..., gt=0)
    started_at_iso: str | None
    finished_at_iso: str | None
    duration_seconds: float = Field(..., ge=0)
    out_classified: str


LeanRunner = Callable[[Path, Path, int], subprocess.CompletedProcess[str]]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_name_fragment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_")
    if not safe:
        safe = "receipt"
    if safe[0].isdigit():
        safe = f"r_{safe}"
    return safe[:80]


def _safe_tactic_fragment(label: str) -> str:
    return _safe_name_fragment(label.replace("?", "_question"))


def _transient_module_text(
    *,
    theorem_name: str,
    imports: list[str],
    statement: str,
    tactic: str,
    bounds: AutomationBounds,
) -> str:
    lines: list[str] = []
    lines.extend(f"import {imp}" for imp in imports)
    lines.append("")
    lines.append(f"set_option maxHeartbeats {bounds.heartbeat_budget}")
    lines.append(f"set_option maxRecDepth {bounds.step_budget}")
    lines.append("")
    lines.append("namespace Solve.Generated.Triviality")
    lines.append("")
    lines.append(f"theorem {theorem_name} :")
    lines.append(f"  ({statement}) := by")
    lines.append(f"  {tactic}")
    lines.append("")
    lines.append("end Solve.Generated.Triviality")
    lines.append("")
    return "\n".join(lines)


def _run_lake_env_lean(path: Path, repo: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [find_tool("lake"), "env", "lean", str(path)],
        cwd=repo,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )


def _attempt_tactic(
    *,
    receipt: CandidateReceipt,
    repo: Path,
    imports: list[str],
    tactic: str,
    bounds: AutomationBounds,
    transient_dir: Path,
    runner: LeanRunner,
) -> AttemptResult:
    theorem_name = f"candidate_{_safe_name_fragment(receipt.record_id)}_{_safe_tactic_fragment(tactic)}"
    module_text = _transient_module_text(
        theorem_name=theorem_name,
        imports=imports,
        statement=receipt.statement.strip(),
        tactic=tactic,
        bounds=bounds,
    )
    module_path = transient_dir / f"Triviality_{theorem_name}.lean"
    module_path.write_text(module_text, encoding="utf-8")
    try:
        completed = runner(module_path, repo, bounds.timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return AttemptResult(tactic=tactic, exit_code=None, stdout=stdout, stderr=stderr, timed_out=True)
    except Exception as exc:  # pragma: no cover - exercised with explicit unit fakes
        return AttemptResult(tactic=tactic, exit_code=None, runner_error=str(exc))
    finally:
        module_path.unlink(missing_ok=True)
    return AttemptResult(
        tactic=tactic,
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _run_import_probe(
    *,
    repo: Path,
    imports: list[str],
    bounds: AutomationBounds,
    transient_dir: Path,
    runner: LeanRunner,
) -> AttemptResult:
    module_text = _transient_module_text(
        theorem_name="import_probe",
        imports=imports,
        statement="True",
        tactic="trivial",
        bounds=bounds,
    )
    module_path = transient_dir / "Triviality_import_probe.lean"
    module_path.write_text(module_text, encoding="utf-8")
    try:
        completed = runner(module_path, repo, bounds.timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return AttemptResult(tactic="import_probe", exit_code=None, stdout=stdout, stderr=stderr, timed_out=True)
    except Exception as exc:  # pragma: no cover - defensive subprocess boundary
        return AttemptResult(tactic="import_probe", exit_code=None, runner_error=str(exc))
    finally:
        module_path.unlink(missing_ok=True)
    return AttemptResult(
        tactic="import_probe",
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _raise_for_failed_probe(result: AttemptResult) -> None:
    if result.closed:
        return
    detail = (result.stdout + result.stderr + (result.runner_error or "")).strip()
    if len(detail) > 500:
        detail = detail[:500] + "..."
    if result.timed_out:
        raise RuntimeError("automation import probe timed out under the configured bound")
    if detail:
        raise RuntimeError(f"automation import probe failed: {detail}")
    raise RuntimeError("automation import probe failed")


def _is_classifiable_retained(receipt: CandidateReceipt) -> bool:
    return receipt.replay_accepted and bool(receipt.statement.strip())


def _statement_can_be_embedded(statement: str) -> bool:
    stripped = statement.strip()
    return bool(stripped) and "\n" not in stripped and "\r" not in stripped


def classify_receipt(
    raw_receipt: dict[str, object],
    *,
    receipt: CandidateReceipt,
    spec: ExperimentSpec,
    repo: Path,
    bounds: AutomationBounds,
    transient_dir: Path,
    runner: LeanRunner = _run_lake_env_lean,
) -> dict[str, object]:
    """Return one classified receipt object, preserving the original fields."""
    classified = dict(raw_receipt)
    attempted: list[str] = []
    closed_by: str | None = None
    saw_infrastructure_error = False

    if not _statement_can_be_embedded(receipt.statement):
        classified.update(
            {
                "automation_attempted": attempted,
                "automation_closed_by": None,
                "automation_heartbeat_budget": bounds.heartbeat_budget,
                "automation_step_budget": bounds.step_budget,
                "automation_classification": AUTOMATION_ERROR,
            }
        )
        return classified

    for tactic in TACTIC_BOUQUET:
        attempted.append(tactic)
        result = _attempt_tactic(
            receipt=receipt,
            repo=repo,
            imports=list(spec.lean.imports),
            tactic=tactic,
            bounds=bounds,
            transient_dir=transient_dir,
            runner=runner,
        )
        if result.infrastructure_error:
            # Fail closed: a runaway/errored tactic must never let a later
            # tactic produce a "closed" classification. Stop immediately.
            saw_infrastructure_error = True
            break
        if result.closed:
            closed_by = tactic
            break

    if saw_infrastructure_error:
        classification: AutomationClassification = AUTOMATION_ERROR
    elif closed_by is not None:
        classification = TRIVIAL_BY_AUTOMATION
    else:
        classification = NOT_TRIVIAL_UNDER_BOUND

    classified.update(
        {
            "automation_attempted": attempted,
            "automation_closed_by": closed_by,
            "automation_heartbeat_budget": bounds.heartbeat_budget,
            "automation_step_budget": bounds.step_budget,
            "automation_classification": classification,
        }
    )
    return classified


def _read_receipt_objects(path: str | Path) -> list[tuple[dict[str, object], CandidateReceipt]]:
    records: list[tuple[dict[str, object], CandidateReceipt]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid receipt JSONL at line {line_no}: {exc}") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"invalid receipt JSONL at line {line_no}: expected object")
            try:
                receipt = CandidateReceipt.model_validate(raw)
            except Exception as exc:
                raise ValueError(f"invalid receipt JSONL at line {line_no}: {exc}") from exc
            records.append((raw, receipt))
    return records


def _write_classified_jsonl(path: str | Path, records: list[dict[str, object]]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    return out


def _write_classification_metrics(path: str | Path, metrics: ClassificationMetrics) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(metrics.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def classify_triviality(
    spec_path: str | Path,
    *,
    repo: Path,
    receipts_path: str | Path,
    out_path: str | Path,
    metrics_path: str | Path | None = None,
    heartbeat_budget: int = 20_000,
    step_budget: int = 1_000,
    timeout_seconds: int = 30,
    max_receipts: int | None = None,
    runner: LeanRunner = _run_lake_env_lean,
) -> ClassificationMetrics:
    if max_receipts is not None and max_receipts < 0:
        raise ValueError("max_receipts must be non-negative")

    repo = repo.resolve()
    started_at_iso = _utc_now_iso()
    start = time.monotonic()
    spec = load_experiment_spec(Path(spec_path) if Path(spec_path).is_absolute() else repo / spec_path)
    bounds = AutomationBounds(
        heartbeat_budget=heartbeat_budget,
        step_budget=step_budget,
        timeout_seconds=timeout_seconds,
    )
    receipt_records = _read_receipt_objects(receipts_path)

    # Receipt/spec integrity: a receipt must come from the same experiment,
    # toolchain, and import set as the spec we classify under. Otherwise the
    # classifier would prove a statement under one import set while preserving
    # receipt fields from another.
    for _raw, receipt in receipt_records:
        if receipt.experiment_id != spec.name:
            raise ValueError(
                f"receipt experiment_id {receipt.experiment_id!r} != spec name {spec.name!r}"
            )
        if receipt.toolchain != spec.lean.toolchain:
            raise ValueError(
                f"receipt toolchain {receipt.toolchain!r} != spec toolchain {spec.lean.toolchain!r}"
            )
        if list(receipt.imports) != list(spec.lean.imports):
            raise ValueError(
                f"receipt imports {receipt.imports!r} != spec imports {spec.lean.imports!r}"
            )

    classified_records: list[dict[str, object]] = []
    skipped_not_retained_count = 0
    cap_skipped_count = 0
    counts_by_classification = {
        TRIVIAL_BY_AUTOMATION: 0,
        NOT_TRIVIAL_UNDER_BOUND: 0,
        AUTOMATION_ERROR: 0,
    }
    counts_by_closed_by: dict[str, int] = {"null": 0}

    with tempfile.TemporaryDirectory(prefix="solve_triviality_") as tmp:
        transient_dir = Path(tmp)
        _raise_for_failed_probe(
            _run_import_probe(
                repo=repo,
                imports=list(spec.lean.imports),
                bounds=bounds,
                transient_dir=transient_dir,
                runner=runner,
            )
        )
        for raw, receipt in receipt_records:
            if not _is_classifiable_retained(receipt):
                skipped_not_retained_count += 1
                continue
            if max_receipts is not None and len(classified_records) >= max_receipts:
                cap_skipped_count += 1
                continue
            classified = classify_receipt(
                raw,
                receipt=receipt,
                spec=spec,
                repo=repo,
                bounds=bounds,
                transient_dir=transient_dir,
                runner=runner,
            )
            classified_records.append(classified)
            classification = str(classified["automation_classification"])
            counts_by_classification[classification] = counts_by_classification.get(classification, 0) + 1
            closed_by = classified["automation_closed_by"]
            closed_key = str(closed_by) if closed_by is not None else "null"
            counts_by_closed_by[closed_key] = counts_by_closed_by.get(closed_key, 0) + 1

    _write_classified_jsonl(out_path, classified_records)
    finished_at_iso = _utc_now_iso()
    metrics = ClassificationMetrics(
        experiment_id=spec.name,
        toolchain=spec.lean.toolchain,
        imports=list(spec.lean.imports),
        total_receipts_read=len(receipt_records),
        retained_receipts_classified=len(classified_records),
        skipped_not_retained_count=skipped_not_retained_count,
        cap_skipped_count=cap_skipped_count,
        counts_by_automation_classification=counts_by_classification,
        counts_by_automation_closed_by=counts_by_closed_by,
        automation_attempted=list(TACTIC_BOUQUET),
        automation_heartbeat_budget=bounds.heartbeat_budget,
        automation_step_budget=bounds.step_budget,
        automation_timeout_seconds=bounds.timeout_seconds,
        started_at_iso=started_at_iso,
        finished_at_iso=finished_at_iso,
        duration_seconds=max(0.0, time.monotonic() - start),
        out_classified=str(out_path),
    )
    if metrics_path is not None:
        _write_classification_metrics(metrics_path, metrics)
    return metrics
