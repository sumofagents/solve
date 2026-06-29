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
from solve.grammar.dispatch import generate_for_operator
from solve.lean.atoms import AtomRecord, enumerate_atoms
from solve.lean.codegen import write_run_control_module
from solve.lean.replay import replay_file
from solve.verify.candidates import GeneratedCandidate, RunControlMetrics, write_metrics
from solve.verify.promoted import PromotedAtomRecord, read_promoted_jsonl
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
    epoch: int = 0,
) -> CandidateReceipt:
    if candidate.operator == "And.intro":
        parent_a, parent_b = candidate.parents
        proof_term = f"And.intro (@{parent_a}) (@{parent_b})"
    else:
        proof_term = candidate.proof_term or ""
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
        interestingness_classification="trivial",
        epoch=epoch,
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


def _promoted_atom_as_atom(record: PromotedAtomRecord) -> AtomRecord:
    return AtomRecord(
        name=record.fully_qualified_name,
        kind="theorem",
        type_pp=record.statement,
        type_hash="sha256:" + hashlib.sha256(record.statement.encode("utf-8")).hexdigest(),
        # TODO(6b): promoted atoms get binder_count=None, which fail-closed excludes from
        # typed-operator selection. Fix in Phase 6b when AtomDump emits a structured binder list.
        binder_count=None,
        arity=None,
        module=record.promoted_module,
        axioms=None,
    )


def _validate_promoted_integrity(records: list[PromotedAtomRecord], spec: ExperimentSpec) -> None:
    for index, record in enumerate(records, start=1):
        if record.experiment_id != spec.name:
            raise ValueError(
                f"promoted row {index} experiment_id {record.experiment_id!r} != spec name {spec.name!r}"
            )
        if record.toolchain != spec.lean.toolchain:
            raise ValueError(
                f"promoted row {index} toolchain {record.toolchain!r} != spec toolchain {spec.lean.toolchain!r}"
            )
        if list(record.imports) != list(spec.lean.imports):
            raise ValueError(
                f"promoted row {index} imports {record.imports!r} != spec imports {spec.lean.imports!r}"
            )


def _epoch1_generated_names(candidates: list[GeneratedCandidate]) -> list[GeneratedCandidate]:
    return [
        candidate.model_copy(
            update={
                "generated_theorem_name": f"Solve.Generated.RunControl.solve_generated_epoch1_{index}",
            }
        )
        for index, candidate in enumerate(candidates)
    ]


def _run_control_generated_names(candidates: list[GeneratedCandidate]) -> list[GeneratedCandidate]:
    return [
        candidate.model_copy(
            update={
                "generated_theorem_name": f"Solve.Generated.RunControl.solve_generated_{index}",
            }
        )
        for index, candidate in enumerate(candidates)
    ]


def run_control(
    spec_path: str,
    *,
    repo: Path,
    out_receipts: Path,
    out_metrics: Path | None,
    max_candidates: int,
    timeout: int = 600,
    epoch: int = 0,
    extend_with: Path | None = None,
) -> RunControlMetrics:
    if max_candidates < 0:
        raise ValueError("max_candidates must be non-negative")
    if epoch not in {0, 1}:
        raise ValueError("epoch must be 0 or 1")
    if epoch == 1 and extend_with is None:
        raise ValueError("extend_with is required when epoch=1")

    repo = repo.resolve()
    started_at_iso = _utc_now_iso()
    start = time.monotonic()
    spec = load_experiment_spec(_resolve_spec_path(spec_path, repo))

    atoms = enumerate_atoms(spec, repo=repo, timeout=timeout)
    extra_imports: list[str] = []
    if epoch == 1 and extend_with is not None:
        promoted_path = extend_with if extend_with.is_absolute() else repo / extend_with
        promoted_records = read_promoted_jsonl(promoted_path)
        _validate_promoted_integrity(promoted_records, spec)
        atoms = [*atoms, *[_promoted_atom_as_atom(record) for record in promoted_records]]
        extra_imports = list(dict.fromkeys(record.promoted_module for record in promoted_records))
    if not any(atom.kind == "theorem" for atom in atoms):
        raise RuntimeError("run-control atom enumeration returned zero theorem records")

    candidate_cap = min(max_candidates, spec.bounds.max_candidates_total)
    candidates: list[GeneratedCandidate] = []
    if candidate_cap > 0:
        operators = sorted(spec.grammar.all_operators)
        per_operator_cap = spec.bounds.max_candidates_per_operator
        # Round-robin interleave so typed operators (Eq.symm/trans, congrArg,
        # Iff.*) get candidates alongside And.intro, not starved by it.
        per_op = max(1, candidate_cap // max(1, len(operators)))
        for operator in operators:
            generated = generate_for_operator(
                operator,
                atoms,
                max_candidates=min(per_op, per_operator_cap),
                experiment_name=spec.name,
            )
            candidates.extend(generated)
            if len(candidates) >= candidate_cap:
                candidates = candidates[:candidate_cap]
                break
    candidates = _run_control_generated_names(candidates)
    if epoch == 1:
        candidates = _epoch1_generated_names(candidates)

    module_suffix = spec.name if epoch == 0 else f"{spec.name}_epoch1"
    module_path = write_run_control_module(
        candidates,
        repo=repo,
        spec=spec,
        module_suffix=module_suffix,
        extra_imports=extra_imports,
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
                module_suffix=f"{module_suffix}_{index}",
                extra_imports=extra_imports,
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
            epoch=epoch,
        )
        for outcome in outcomes
    ]
    write_jsonl(out_receipts, receipts)

    # Rewrite the module with only retained candidates so downstream tools
    # (classify-value, promote, mark-downstream-used) can build it cleanly.
    # The aggregate module may contain type-mismatched typed-operator candidates
    # that fail lake build; the clean module only includes replay-accepted defs.
    retained_candidates = [outcome.candidate for outcome in outcomes if outcome.retained]
    if retained_candidates:
        write_run_control_module(
            retained_candidates,
            repo=repo,
            spec=spec,
            module_suffix=module_suffix,
            extra_imports=extra_imports,
        )

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
