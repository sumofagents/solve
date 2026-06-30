"""Proof-shortening measurement orchestrator.

Given a benchmarks JSONL file where each row names a baseline proof and a
with-promoted proof of the same proposition, compare their elaborated proof
expression sizes via :mod:`solve.lean.proof_size`.

Verdict rules:

* If either probe returns ``unknown`` => row verdict ``unknown``.
* If ``promoted_const`` is set and the with-promoted proof does NOT actually
  use that constant => row verdict ``unknown`` (do not claim shortening for
  proofs that didn't really use the promoted theorem).
* Else if ``with_size < without_size`` => ``shorter``.
* Else => ``not_shorter``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Literal, Optional

from solve.lean.proof_size import ProofSizeResult, probe_proof_size


@dataclass(frozen=True)
class BenchmarkRow:
    benchmark_id: str
    imports: tuple
    without_target: str
    with_target: str
    promoted_const: Optional[str] = None


@dataclass
class ShorteningRow:
    benchmark_id: str
    without_target: str
    with_target: str
    promoted_const: Optional[str]
    without_size: Optional[int]
    with_size: Optional[int]
    delta_absolute: Optional[int]
    delta_ratio: Optional[float]
    used_promoted_in_with: Optional[bool]
    verdict: Literal["shorter", "not_shorter", "unknown"]
    reason: str


@dataclass
class ShorteningMetrics:
    total: int
    counts_by_verdict: dict
    shortened_count: int
    unknown_count: int


ProbeFn = Callable[..., ProofSizeResult]


def load_benchmarks(path: Path) -> List[BenchmarkRow]:
    rows: List[BenchmarkRow] = []
    text = Path(path).read_text(encoding="utf-8")
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"benchmarks line {line_no} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"benchmarks line {line_no} must be an object")
        try:
            rows.append(
                BenchmarkRow(
                    benchmark_id=str(payload["benchmark_id"]),
                    imports=tuple(payload.get("imports") or ()),
                    without_target=str(payload["without_target"]),
                    with_target=str(payload["with_target"]),
                    promoted_const=(
                        str(payload["promoted_const"])
                        if payload.get("promoted_const") not in (None, "")
                        else None
                    ),
                )
            )
        except KeyError as exc:
            raise RuntimeError(
                f"benchmarks line {line_no} missing required key {exc}"
            ) from exc
    return rows


def _compute_row(
    bench: BenchmarkRow,
    without_result: ProofSizeResult,
    with_result: ProofSizeResult,
) -> ShorteningRow:
    promoted_const = bench.promoted_const
    used_promoted_in_with: Optional[bool]
    if promoted_const is None:
        used_promoted_in_with = None
    else:
        used_promoted_in_with = (
            with_result.used_required_const
            if with_result.verdict == "ok"
            else None
        )

    # Verdict resolution
    if without_result.verdict != "ok" or with_result.verdict != "ok" or without_result.term_size is None or with_result.term_size is None:
        verdict = "unknown"
        reasons = []
        if without_result.verdict != "ok":
            reasons.append(f"without:{without_result.reason or 'unknown'}")
        if with_result.verdict != "ok":
            reasons.append(f"with:{with_result.reason or 'unknown'}")
        if without_result.verdict == "ok" and without_result.term_size is None:
            reasons.append("without:ok payload missing term_size")
        if with_result.verdict == "ok" and with_result.term_size is None:
            reasons.append("with:ok payload missing term_size")
        reason = "; ".join(reasons) or "probe unknown"
        return ShorteningRow(
            benchmark_id=bench.benchmark_id,
            without_target=bench.without_target,
            with_target=bench.with_target,
            promoted_const=promoted_const,
            without_size=without_result.term_size,
            with_size=with_result.term_size,
            delta_absolute=None,
            delta_ratio=None,
            used_promoted_in_with=used_promoted_in_with,
            verdict=verdict,
            reason=reason,
        )

    without_size = without_result.term_size or 0
    with_size = with_result.term_size or 0
    delta_absolute = without_size - with_size
    delta_ratio = (delta_absolute / without_size) if without_size > 0 else None

    if promoted_const is not None and used_promoted_in_with is not True:
        return ShorteningRow(
            benchmark_id=bench.benchmark_id,
            without_target=bench.without_target,
            with_target=bench.with_target,
            promoted_const=promoted_const,
            without_size=without_size,
            with_size=with_size,
            delta_absolute=delta_absolute,
            delta_ratio=delta_ratio,
            used_promoted_in_with=used_promoted_in_with,
            verdict="unknown",
            reason=f"with-target does not use promoted_const {promoted_const}",
        )

    if with_size < without_size:
        verdict = "shorter"
        reason = "with-target proof expression smaller than baseline"
    else:
        verdict = "not_shorter"
        reason = "with-target proof expression not smaller than baseline"

    return ShorteningRow(
        benchmark_id=bench.benchmark_id,
        without_target=bench.without_target,
        with_target=bench.with_target,
        promoted_const=promoted_const,
        without_size=without_size,
        with_size=with_size,
        delta_absolute=delta_absolute,
        delta_ratio=delta_ratio,
        used_promoted_in_with=used_promoted_in_with,
        verdict=verdict,
        reason=reason,
    )


def measure_shortening(
    benchmarks: Iterable[BenchmarkRow],
    *,
    repo: Path,
    timeout: int = 60,
    heartbeat_budget: int = 20_000,
    rec_depth: int = 1_000,
    probe_fn: Optional[ProbeFn] = None,
) -> List[ShorteningRow]:
    # Resolve probe at call time so monkeypatches against
    # ``solve.measure_shortening.probe_proof_size`` take effect.
    if probe_fn is None:
        import solve.measure_shortening as _self

        probe_fn = _self.probe_proof_size
    rows: List[ShorteningRow] = []
    for bench in benchmarks:
        imports_list = list(bench.imports)
        without_result = probe_fn(
            bench.without_target,
            repo=repo,
            imports=imports_list,
            required_const=None,
            timeout=timeout,
            heartbeat_budget=heartbeat_budget,
            rec_depth=rec_depth,
        )
        with_result = probe_fn(
            bench.with_target,
            repo=repo,
            imports=imports_list,
            required_const=bench.promoted_const,
            timeout=timeout,
            heartbeat_budget=heartbeat_budget,
            rec_depth=rec_depth,
        )
        rows.append(_compute_row(bench, without_result, with_result))
    return rows


def summarize(rows: Iterable[ShorteningRow]) -> ShorteningMetrics:
    counts: dict = {}
    total = 0
    shortened = 0
    unknown = 0
    for row in rows:
        total += 1
        counts[row.verdict] = counts.get(row.verdict, 0) + 1
        if row.verdict == "shorter":
            shortened += 1
        elif row.verdict == "unknown":
            unknown += 1
    return ShorteningMetrics(
        total=total,
        counts_by_verdict=counts,
        shortened_count=shortened,
        unknown_count=unknown,
    )


def write_rows(path: Path, rows: Iterable[ShorteningRow]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(asdict(row), sort_keys=True) + "\n")
    return path


def write_metrics(path: Path, metrics: ShorteningMetrics) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(metrics), sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path
