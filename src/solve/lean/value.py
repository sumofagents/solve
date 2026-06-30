"""Four-axis value classification for replay-retained receipts."""

from __future__ import annotations

import json
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from solve.experiments.spec import ExperimentSpec, load_experiment_spec
from solve.lean.novelty import NoveltyProbeResult, NoveltyScope, NoveltyVerifyMode, probe_novelty_batch
from solve.lean.replay import build_modules, find_tool
from solve.lean.term_inspect import StructuralProbeResult, probe_structural_packaging_details
from solve.lean.triviality import (
    AutomationBounds,
    _is_classifiable_retained,
    _raise_for_failed_probe,
    _read_receipt_objects,
    _run_import_probe,
    _run_lake_env_lean,
    classify_from_scratch_closure,
    classify_ingredient_triviality,
)
from solve.verify.candidates import StrictFrozenModel
from solve.verify.receipts import CandidateReceipt


@dataclass(frozen=True)
class ValueGate:
    truth: bool
    novelty: bool
    trivial: bool
    promotable: bool
    interesting: bool
    interestingness_classification: str


class ValueClassificationMetrics(StrictFrozenModel):
    experiment_id: str = Field(..., min_length=1)
    toolchain: str = Field(..., min_length=1)
    imports: list[str]
    total_receipts_read: int = Field(..., ge=0)
    retained_receipts_classified: int = Field(..., ge=0)
    skipped_not_retained_count: int = Field(..., ge=0)
    cap_skipped_count: int = Field(..., ge=0)
    counts_by_structural_packaging: dict[str, int]
    counts_by_ingredient_trivial: dict[str, int]
    counts_by_ingredient_closed_by: dict[str, int]
    counts_by_novelty_classification: dict[str, int]
    counts_by_from_scratch_closure: dict[str, int]
    counts_by_promotable: dict[str, int]
    structural_heartbeat_budget: int = Field(..., gt=0)
    structural_step_budget: int = Field(..., gt=0)
    structural_timeout_seconds: int = Field(..., gt=0)
    ingredient_heartbeat_budget: int = Field(..., gt=0)
    ingredient_step_budget: int = Field(..., gt=0)
    ingredient_timeout_seconds: int = Field(..., gt=0)
    novelty_candidate_cap: int = Field(..., ge=0)
    novelty_heartbeat_budget: int = Field(..., gt=0)
    novelty_step_budget: int = Field(..., gt=0)
    novelty_timeout_seconds: int = Field(..., gt=0)
    novelty_scope: str = "imported"
    from_scratch_heartbeat_budget: int = Field(..., gt=0)
    from_scratch_step_budget: int = Field(..., gt=0)
    from_scratch_timeout_seconds: int = Field(..., gt=0)
    started_at_iso: str | None
    finished_at_iso: str | None
    duration_seconds: float = Field(..., ge=0)
    out_classified: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_jsonl(path: str | Path, records: list[dict[str, object]]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    return out


def _write_metrics(path: str | Path, metrics: ValueClassificationMetrics) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(metrics.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def _safe_generated_suffix(name: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_")
    if not suffix:
        suffix = "spec"
    if suffix[0].isdigit():
        suffix = f"spec_{suffix}"
    return suffix


def _run_control_module_import(spec: ExperimentSpec, *, epoch: int = 0) -> str:
    suffix = spec.name if epoch == 0 else f"{spec.name}_epoch{epoch}"
    return f"Solve.Generated.RunControl_{_safe_generated_suffix(suffix)}"


def _run_control_imports_for_receipts(
    spec: ExperimentSpec,
    receipts: list[tuple[dict[str, object], CandidateReceipt]],
) -> list[str]:
    imports: list[str] = []
    for _raw, receipt in receipts:
        module = _run_control_module_import(spec, epoch=receipt.epoch)
        if module not in imports:
            imports.append(module)
    return imports or [_run_control_module_import(spec)]


def _validate_receipt_integrity(receipts: list[tuple[dict[str, object], CandidateReceipt]], spec: ExperimentSpec) -> None:
    for _raw, receipt in receipts:
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


def compose_value_gate(
    *,
    truth: bool,
    novelty_classification: str,
    structural_packaging: bool | None,
    ingredient_trivial_by_automation: bool | None,
    downstream_used: bool | None,
) -> ValueGate:
    novelty = novelty_classification == "novel_in_imported_env"
    trivial = structural_packaging is True or ingredient_trivial_by_automation is True
    # Fail-closed: if any probe errored (returned None), we cannot confirm
    # non-triviality, so we must not promote. Only promote when both probes
    # returned definite results AND neither found triviality.
    probe_uncertain = structural_packaging is None or ingredient_trivial_by_automation is None
    promotable = truth and novelty and not trivial and not probe_uncertain
    interesting = promotable and downstream_used is True
    if interesting:
        interestingness_classification = "downstream_used"
    elif trivial:
        interestingness_classification = "trivial"
    else:
        interestingness_classification = "unknown"
    return ValueGate(
        truth=truth,
        novelty=novelty,
        trivial=trivial,
        promotable=promotable,
        interesting=interesting,
        interestingness_classification=interestingness_classification,
    )


def _bool_key(value: bool | None) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "unknown"


def _structural_count_key(result: StructuralProbeResult) -> str:
    if result.verdict == "error":
        return "unknown"
    return "true" if result.structural_packaging else "false"


def _missing_novelty_result(target: str) -> NoveltyProbeResult:
    return NoveltyProbeResult(
        classification="unknown",
        witness=None,
        compared=0,
        cap_hit=False,
        reason=f"probe_error: missing NOV result for target {target}",
    )


def _count(mapping: dict[str, int], key: str) -> None:
    mapping[key] = mapping.get(key, 0) + 1


def classify_value(
    spec_path: str | Path,
    *,
    repo: Path,
    receipts_path: str | Path,
    out_path: str | Path,
    metrics_path: str | Path,
    heartbeat_budget: int = 20_000,
    step_budget: int = 1_000,
    timeout_seconds: int = 30,
    novelty_candidate_cap: int = 500_000,
    novelty_heartbeat_budget: int = 2_000_000,
    novelty_timeout_seconds: int = 60,
    novelty_global_timeout_seconds: int = 900,
    novelty_scope: NoveltyScope = "imported",
    novelty_verify_mode: NoveltyVerifyMode = "brute",
    max_receipts: int | None = None,
    promoted_prefixes: list[str] | None = None,
) -> ValueClassificationMetrics:
    if max_receipts is not None and max_receipts < 0:
        raise ValueError("max_receipts must be non-negative")
    if novelty_candidate_cap < 0:
        raise ValueError("novelty_candidate_cap must be non-negative")
    if novelty_global_timeout_seconds <= 0:
        raise ValueError("novelty_global_timeout_seconds must be positive")
    if novelty_scope not in {"imported", "global"}:
        raise ValueError("novelty_scope must be 'imported' or 'global'")
    if novelty_verify_mode not in {"discrtree", "brute"}:
        raise ValueError("novelty_verify_mode must be 'discrtree' or 'brute'")

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
    _validate_receipt_integrity(receipt_records, spec)

    classified_records: list[dict[str, object]] = []
    skipped_not_retained_count = 0
    cap_skipped_count = 0
    records_to_classify: list[tuple[dict[str, object], CandidateReceipt]] = []
    for raw, receipt in receipt_records:
        if not _is_classifiable_retained(receipt):
            skipped_not_retained_count += 1
            continue
        if max_receipts is not None and len(records_to_classify) >= max_receipts:
            cap_skipped_count += 1
            continue
        records_to_classify.append((raw, receipt))

    probe_imports = _run_control_imports_for_receipts(spec, records_to_classify)
    if records_to_classify:
        build_modules(repo, [*probe_imports, "Solve.Tools.NoveltyProbe", "Solve.Tools.TermProbe"])

    counts_by_structural = {"true": 0, "false": 0, "unknown": 0}
    counts_by_ingredient = {"true": 0, "false": 0, "unknown": 0}
    counts_by_ingredient_closed_by: dict[str, int] = {"null": 0}
    counts_by_novelty = {
        "unknown": 0,
        "existing_defeq_duplicate": 0,
        "novel_in_imported_env": 0,
    }
    counts_by_from_scratch = {
        "closed": 0,
        "not_closed": 0,
        "timeout": 0,
        "error": 0,
        "unknown": 0,
    }
    counts_by_promotable = {"true": 0, "false": 0}
    if records_to_classify:
        novelty_timeout = novelty_global_timeout_seconds if novelty_scope == "global" else novelty_timeout_seconds
        target_names = [receipt.generated_theorem_name for _raw, receipt in records_to_classify]
        novelty_results = probe_novelty_batch(
            target_names,
            repo=repo,
            imports=probe_imports,
            prefixes=list(spec.corpus.namespace_prefixes),
            scope=novelty_scope,
            verify_mode=novelty_verify_mode,
            promoted_prefixes=promoted_prefixes,
            candidate_cap=novelty_candidate_cap,
            timeout=novelty_timeout,
            heartbeat_budget=novelty_heartbeat_budget,
            rec_depth=step_budget,
        )
        with tempfile.TemporaryDirectory(prefix="solve_value_") as tmp:
            transient_dir = Path(tmp)
            _raise_for_failed_probe(
                _run_import_probe(
                    repo=repo,
                    imports=list(spec.lean.imports),
                    bounds=bounds,
                    transient_dir=transient_dir,
                    runner=_run_lake_env_lean,
                )
            )
            for raw, receipt in records_to_classify:
                classified = dict(raw)
                structural_result = probe_structural_packaging_details(
                    receipt.generated_theorem_name,
                    repo=repo,
                    imports=probe_imports,
                    timeout=timeout_seconds,
                    heartbeat_budget=heartbeat_budget,
                    rec_depth=step_budget,
                )
                structural_packaging = (
                    structural_result.structural_packaging if structural_result.verdict != "error" else None
                )
                classified.update(
                    {
                        "structural_packaging": structural_packaging,
                        "structural_packaging_reason": structural_result.reason,
                    }
                )
                _count(counts_by_structural, _structural_count_key(structural_result))

                classified = classify_ingredient_triviality(
                    classified,
                    receipt=receipt,
                    spec=spec,
                    repo=repo,
                    bounds=bounds,
                    transient_dir=transient_dir,
                )
                ingredient_trivial = classified.get("ingredient_trivial_by_automation")
                _count(
                    counts_by_ingredient,
                    _bool_key(ingredient_trivial if isinstance(ingredient_trivial, bool) else None),
                )
                ingredient_closed_by = classified.get("ingredient_trivial_closed_by")
                _count(counts_by_ingredient_closed_by, str(ingredient_closed_by) if ingredient_closed_by else "null")

                novelty_result: NoveltyProbeResult = novelty_results.get(
                    receipt.generated_theorem_name,
                    _missing_novelty_result(receipt.generated_theorem_name),
                )
                classified["novelty_classification"] = novelty_result.classification
                classified["novelty_witness"] = novelty_result.witness
                classified["novelty_compared"] = novelty_result.compared
                classified["novelty_cap_hit"] = novelty_result.cap_hit
                classified["novelty_reason"] = novelty_result.reason
                _count(counts_by_novelty, novelty_result.classification)

                classified = classify_from_scratch_closure(
                    classified,
                    receipt=receipt,
                    spec=spec,
                    repo=repo,
                    bounds=bounds,
                    transient_dir=transient_dir,
                )
                from_scratch = str(classified.get("from_scratch_closure") or "unknown")
                _count(counts_by_from_scratch, from_scratch)

                gate = compose_value_gate(
                    truth=receipt.replay_accepted,
                    novelty_classification=novelty_result.classification,
                    structural_packaging=structural_packaging,
                    ingredient_trivial_by_automation=(
                        ingredient_trivial if isinstance(ingredient_trivial, bool) else None
                    ),
                    downstream_used=receipt.downstream_used,
                )
                classified["promotable"] = gate.promotable
                classified["downstream_used"] = receipt.downstream_used
                classified["interestingness_classification"] = gate.interestingness_classification
                _count(counts_by_promotable, "true" if gate.promotable else "false")
                classified_records.append(classified)

    _write_jsonl(out_path, classified_records)
    finished_at_iso = _utc_now_iso()
    metrics = ValueClassificationMetrics(
        experiment_id=spec.name,
        toolchain=spec.lean.toolchain,
        imports=list(spec.lean.imports),
        total_receipts_read=len(receipt_records),
        retained_receipts_classified=len(classified_records),
        skipped_not_retained_count=skipped_not_retained_count,
        cap_skipped_count=cap_skipped_count,
        counts_by_structural_packaging=counts_by_structural,
        counts_by_ingredient_trivial=counts_by_ingredient,
        counts_by_ingredient_closed_by=counts_by_ingredient_closed_by,
        counts_by_novelty_classification=counts_by_novelty,
        counts_by_from_scratch_closure=counts_by_from_scratch,
        counts_by_promotable=counts_by_promotable,
        structural_heartbeat_budget=heartbeat_budget,
        structural_step_budget=step_budget,
        structural_timeout_seconds=timeout_seconds,
        ingredient_heartbeat_budget=heartbeat_budget,
        ingredient_step_budget=step_budget,
        ingredient_timeout_seconds=timeout_seconds,
        novelty_candidate_cap=novelty_candidate_cap,
        novelty_heartbeat_budget=novelty_heartbeat_budget,
        novelty_step_budget=step_budget,
        novelty_timeout_seconds=novelty_global_timeout_seconds if novelty_scope == "global" else novelty_timeout_seconds,
        novelty_scope=novelty_scope,
        from_scratch_heartbeat_budget=heartbeat_budget,
        from_scratch_step_budget=step_budget,
        from_scratch_timeout_seconds=timeout_seconds,
        started_at_iso=started_at_iso,
        finished_at_iso=finished_at_iso,
        duration_seconds=max(0.0, time.monotonic() - start),
        out_classified=str(out_path),
    )
    _write_metrics(metrics_path, metrics)
    return metrics
