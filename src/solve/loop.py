"""Core loop boundary.

This module is intentionally connector-free. Language connectors may prepare
ExperimentSpec values and explain receipts, but they are not imported by the
retention/replay path.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from solve.experiments.spec import ExperimentSpec, load_experiment_spec
from solve.grammar.and_intro import generate_and_intro_candidates
from solve.lean.atoms import enumerate_atoms
from solve.lean.codegen import write_run_control_module
from solve.lean.replay import replay_file
from solve.verify.candidates import GeneratedCandidate, RunControlMetrics, write_metrics
from solve.verify.receipts import CandidateReceipt, ReplayResult, write_jsonl


def retention_gate_summary(spec: ExperimentSpec) -> dict[str, object]:
    """Return the mechanical gates a run must satisfy before promotion."""
    return {
        "experiment": spec.name,
        "requires_replay": spec.promotion.require_replay,
        "requires_not_existing_defeq": spec.promotion.require_not_existing_defeq,
        "operators": spec.grammar.all_operators,
    }


_DEPENDS_RE = re.compile(r"^'?([^']+)'?\s+depends on axioms:\s*\[(.*)\]\s*$")
_NO_AXIOMS_RE = re.compile(r"^'?([^']+)'?\s+does not depend on any axioms\s*$")
_CHECK_RE = re.compile(r"^'?([^']+)'?\s*:\s*(.*)$")
_UNIVERSE_SUFFIX_RE = re.compile(r"\.\{.*\}$")


@dataclass(frozen=True)
class _CandidateReplay:
    candidate: GeneratedCandidate
    replay: ReplayResult
    statement: str
    axioms_used: list[str]
    retained: bool


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _replay_result_from_completed(result: object) -> ReplayResult:
    args = getattr(result, "args")
    if isinstance(args, list):
        command = [str(part) for part in args]
    elif isinstance(args, tuple):
        command = [str(part) for part in args]
    else:
        command = [str(args)]
    return ReplayResult(
        command=command,
        exit_code=int(getattr(result, "returncode")),
        stdout=str(getattr(result, "stdout") or ""),
        stderr=str(getattr(result, "stderr") or ""),
    )


def _parse_axioms(stdout: str) -> dict[str, list[str]]:
    by_name: dict[str, list[str]] = {}
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        no_axioms = _NO_AXIOMS_RE.match(line)
        if no_axioms:
            by_name[no_axioms.group(1)] = []
            continue
        depends = _DEPENDS_RE.match(line)
        if depends:
            raw_axioms = depends.group(2).strip()
            axioms = [] if not raw_axioms else [axiom.strip() for axiom in raw_axioms.split(",") if axiom.strip()]
            by_name[depends.group(1)] = axioms
    return by_name


def _parse_checked_statements(stdout: str) -> dict[str, str]:
    by_name: dict[str, str] = {}

    current_name: str | None = None
    current_lines: list[str] = []

    def flush_current() -> None:
        nonlocal current_name, current_lines
        if current_name is not None:
            statement = " ".join(part.strip() for part in current_lines if part.strip()).strip()
            if statement:
                by_name[current_name] = statement
        current_name = None
        current_lines = []

    for raw_line in stdout.splitlines():
        if current_name is not None and (raw_line.startswith(" ") or raw_line.startswith("\t")):
            current_lines.append(raw_line)
            continue

        flush_current()
        checked = _CHECK_RE.match(raw_line.strip())
        if checked:
            name = _UNIVERSE_SUFFIX_RE.sub("", checked.group(1).strip())
            tail = checked.group(2).strip()
            if tail:
                by_name[name] = tail
            else:
                current_name = name
                current_lines = []

    flush_current()
    return by_name


def _receipt_for(
    *,
    candidate: GeneratedCandidate,
    spec: ExperimentSpec,
    replay: ReplayResult,
    axioms_used: list[str],
    statement: str,
) -> CandidateReceipt:
    parent_a, parent_b = candidate.parents
    proof_term = f"And.intro (@{parent_a}) (@{parent_b})"
    normalized_hash = "sha256:" + hashlib.sha256(statement.encode("utf-8")).hexdigest()
    return CandidateReceipt(
        record_id=candidate.candidate_id,
        experiment_id=spec.name,
        toolchain=spec.lean.toolchain,
        imports=list(spec.lean.imports),
        statement=statement,
        proof_term=proof_term,
        generated_theorem_name=candidate.generated_theorem_name,
        parents=list(candidate.parents),
        operator=candidate.operator,
        depth=candidate.depth,
        normalized_statement_hash=normalized_hash,
        axioms_used=axioms_used,
        replay=replay,
        novelty_classification="unknown",
        interestingness_classification="trivial",
    )


def _outcomes_from_single_replay(
    candidates: list[GeneratedCandidate],
    replay: ReplayResult,
) -> list[_CandidateReplay]:
    axioms_by_name = _parse_axioms(replay.stdout)
    statements_by_name = _parse_checked_statements(replay.stdout)
    outcomes: list[_CandidateReplay] = []
    for candidate in candidates:
        has_axioms_line = candidate.generated_theorem_name in axioms_by_name
        statement = statements_by_name.get(candidate.generated_theorem_name, "")
        outcomes.append(
            _CandidateReplay(
                candidate=candidate,
                replay=replay,
                statement=statement,
                axioms_used=axioms_by_name.get(candidate.generated_theorem_name, []),
                retained=replay.accepted and has_axioms_line and bool(statement),
            )
        )
    return outcomes


def _resolve_spec_path(spec_path: str, repo: Path) -> Path:
    path = Path(spec_path)
    if path.is_absolute() or path.exists():
        return path
    return repo / path


def run_control(
    spec_path: str,
    *,
    repo: Path,
    out_receipts: Path,
    out_metrics: Path | None,
    max_candidates: int,
    timeout: int = 600,
) -> RunControlMetrics:
    if max_candidates < 0:
        raise ValueError("max_candidates must be non-negative")

    repo = repo.resolve()
    started_at_iso = _utc_now_iso()
    start = time.monotonic()
    spec = load_experiment_spec(_resolve_spec_path(spec_path, repo))

    atoms = enumerate_atoms(spec, repo=repo, timeout=timeout)
    if not any(atom.kind == "theorem" for atom in atoms):
        raise RuntimeError("run-control atom enumeration returned zero theorem records")

    candidate_cap = min(max_candidates, spec.bounds.max_candidates_total, spec.bounds.max_candidates_per_operator)
    candidates = generate_and_intro_candidates(
        atoms,
        max_candidates=candidate_cap,
        experiment_name=spec.name,
    )

    module_path = write_run_control_module(
        candidates,
        repo=repo,
        spec=spec,
        module_suffix=spec.name,
    )
    aggregate_replay = _replay_result_from_completed(replay_file(module_path, cwd=repo, timeout=timeout))
    if aggregate_replay.accepted:
        outcomes = _outcomes_from_single_replay(candidates, aggregate_replay)
    else:
        outcomes = []
        for index, candidate in enumerate(candidates):
            per_candidate_module = write_run_control_module(
                [candidate],
                repo=repo,
                spec=spec,
                module_suffix=f"{spec.name}_{index}",
            )
            replay = _replay_result_from_completed(replay_file(per_candidate_module, cwd=repo, timeout=timeout))
            outcomes.extend(_outcomes_from_single_replay([candidate], replay))

    receipts = [
        _receipt_for(
            candidate=outcome.candidate,
            spec=spec,
            replay=outcome.replay,
            axioms_used=outcome.axioms_used,
            statement=outcome.statement,
        )
        for outcome in outcomes
    ]
    write_jsonl(out_receipts, receipts)

    retained_count = sum(1 for outcome in outcomes if outcome.retained)
    finished_at_iso = _utc_now_iso()
    metrics = RunControlMetrics(
        experiment_id=spec.name,
        toolchain=spec.lean.toolchain,
        imports=list(spec.lean.imports),
        candidate_count=len(candidates),
        replay_attempted_count=len(candidates),
        replay_accepted_count=retained_count,
        retained_count=retained_count,
        trivial_count=retained_count,
        structural_count=retained_count,
        started_at_iso=started_at_iso,
        finished_at_iso=finished_at_iso,
        duration_seconds=max(0.0, time.monotonic() - start),
        out_receipts=str(out_receipts),
    )
    if out_metrics is not None:
        write_metrics(out_metrics, metrics)
    return metrics
