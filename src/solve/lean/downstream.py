"""Mark epoch-0 receipts whose promoted atoms are used by retained epoch-1 receipts."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from solve.experiments.spec import ExperimentSpec, load_experiment_spec
from solve.lean.usage import probe_usage
from solve.verify.promoted import PromotedAtomRecord, read_promoted_jsonl
from solve.verify.receipts import CandidateReceipt, read_jsonl, write_jsonl


@dataclass(frozen=True)
class DownstreamUsedSummary:
    epoch0: Path
    promoted: int
    used: int
    consumers: int
    probe_unknown: int


def is_self_reference(consumer_parents: list[str], candidate_fqn: str, promoted_fqns: set[str]) -> bool:
    """Only filter when the consumer's parents are EXCLUSIVELY the promoted atom.

    A candidate with parents [promoted_atom, other_seed_atom] genuinely uses
    the promoted atom downstream — that must NOT be filtered. Only the trivial
    case where the consumer is JUST a repackaging of the promoted atom alone
    (all parents == candidate_fqn) is self-referential noise.
    """
    return len(consumer_parents) > 0 and all(p == candidate_fqn for p in consumer_parents)


def _load_spec(spec_path: str | Path, repo: Path) -> ExperimentSpec:
    path = Path(spec_path)
    if not path.is_absolute():
        path = repo / path
    return load_experiment_spec(path)


def _validate_receipts(receipts: list[CandidateReceipt], spec: ExperimentSpec, *, epoch: int) -> None:
    for receipt in receipts:
        if receipt.epoch != epoch:
            raise ValueError(f"receipt {receipt.record_id!r} epoch {receipt.epoch} != expected {epoch}")
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


def _promoted_maps(
    promoted_records: list[PromotedAtomRecord],
) -> tuple[dict[str, PromotedAtomRecord], dict[str, str]]:
    promoted_by_fqn: dict[str, PromotedAtomRecord] = {}
    promoted_to_epoch0_record_id: dict[str, str] = {}
    for record in promoted_records:
        fqn = f"{record.promoted_module}.{record.local_name}"
        if fqn != record.fully_qualified_name:
            raise ValueError(
                f"promoted record {record.record_id!r} FQN mismatch: "
                f"{fqn!r} != {record.fully_qualified_name!r}"
            )
        if fqn in promoted_by_fqn:
            raise ValueError(f"duplicate promoted FQN {fqn!r}")
        promoted_by_fqn[fqn] = record
        promoted_to_epoch0_record_id[fqn] = record.source_record_id
    return promoted_by_fqn, promoted_to_epoch0_record_id


def _atomic_write_epoch0(path: Path, receipts: list[CandidateReceipt]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        write_jsonl(tmp, receipts)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def mark_downstream_used(
    spec_path: str | Path,
    *,
    repo: Path,
    epoch0_receipts_path: str | Path,
    epoch1_receipts_path: str | Path,
    promoted_path: str | Path,
    timeout: int = 60,
    heartbeat_budget: int = 20_000,
    rec_depth: int = 1_000,
    max_constants: int = 10_000,
    max_receipts: int | None = None,
    stderr: TextIO | None = None,
) -> DownstreamUsedSummary:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if heartbeat_budget <= 0:
        raise ValueError("heartbeat_budget must be positive")
    if rec_depth <= 0:
        raise ValueError("rec_depth must be positive")
    if max_constants <= 0:
        raise ValueError("max_constants must be positive")
    if max_receipts is not None and max_receipts < 0:
        raise ValueError("max_receipts must be non-negative")

    repo = repo.resolve()
    if stderr is None:
        stderr = sys.stderr
    spec = _load_spec(spec_path, repo)
    epoch0_path = Path(epoch0_receipts_path)
    epoch1_path = Path(epoch1_receipts_path)
    promoted_jsonl_path = Path(promoted_path)
    if not epoch0_path.is_absolute():
        epoch0_path = repo / epoch0_path
    if not epoch1_path.is_absolute():
        epoch1_path = repo / epoch1_path
    if not promoted_jsonl_path.is_absolute():
        promoted_jsonl_path = repo / promoted_jsonl_path

    epoch0_receipts = read_jsonl(epoch0_path)
    epoch1_receipts = read_jsonl(epoch1_path)
    promoted_records = read_promoted_jsonl(promoted_jsonl_path)
    _validate_receipts(epoch0_receipts, spec, epoch=0)
    _validate_receipts(epoch1_receipts, spec, epoch=1)
    promoted_by_fqn, promoted_to_epoch0_record_id = _promoted_maps(promoted_records)
    promoted_fqns = set(promoted_by_fqn)

    epoch0_index_by_record_id: dict[str, int] = {}
    for index, receipt in enumerate(epoch0_receipts):
        if receipt.record_id in epoch0_index_by_record_id:
            raise ValueError(f"duplicate epoch-0 receipt record_id {receipt.record_id!r}")
        epoch0_index_by_record_id[receipt.record_id] = index

    consumers_by_promoted: dict[str, set[str]] = {}
    probe_unknown = 0
    retained_processed = 0
    if promoted_fqns:
        for receipt in epoch1_receipts:
            # Only retained epoch-1 receipts count.
            if not receipt.replay_accepted:
                continue
            if max_receipts is not None and retained_processed >= max_receipts:
                break
            retained_processed += 1
            # Derive the RunControl module that declares this target constant.
            # Epoch-1 candidates live in Solve.Generated.RunControl_<spec>_epoch1.
            # The receipt's imports carry spec.lean.imports (e.g. Mathlib...),
            # not the generated module — the probe needs both to find the constant.
            from solve.lean.promote_codegen import source_run_control_module_name
            epoch1_module = f"{source_run_control_module_name(spec)}_epoch1"
            probe_imports = list(receipt.imports) + [epoch1_module]
            # Kernel is sole oracle: Python supplies candidate names but never scans proof-term source.
            # Bounded: each probe carries heartbeat, recursion-depth, subprocess timeout, and constant-cap limits.
            result = probe_usage(
                receipt.generated_theorem_name,
                repo=repo,
                imports=probe_imports,
                promoted_names=list(promoted_by_fqn.keys()),
                timeout=timeout,
                heartbeat_budget=heartbeat_budget,
                rec_depth=rec_depth,
                max_constants=max_constants,
            )
            if result.unknown:
                # Probe failure -> False/unknown, never True.
                probe_unknown += 1
                print(
                    f"DOWNSTREAM_USED_PROBE_UNKNOWN {receipt.generated_theorem_name} reason={result.reason}",
                    file=stderr,
                )
                continue
            for candidate_fqn in set(result.used_promoted):
                if candidate_fqn not in promoted_by_fqn:
                    continue
                if is_self_reference(receipt.parents, candidate_fqn, promoted_fqns):
                    continue
                consumers_by_promoted.setdefault(candidate_fqn, set()).add(receipt.generated_theorem_name)

    updated_receipts = list(epoch0_receipts)
    for promoted_fqn, consumers in consumers_by_promoted.items():
        if not consumers:
            continue
        source_record_id = promoted_to_epoch0_record_id[promoted_fqn]
        if source_record_id not in epoch0_index_by_record_id:
            raise ValueError(
                f"promoted FQN {promoted_fqn!r} references missing epoch-0 receipt {source_record_id!r}"
            )
        index = epoch0_index_by_record_id[source_record_id]
        updated_receipts[index] = updated_receipts[index].model_copy(
            update={
                "downstream_used": True,
                "downstream_used_by": sorted(consumers),
            }
        )

    _atomic_write_epoch0(epoch0_path, updated_receipts)
    consumer_names = {consumer for consumers in consumers_by_promoted.values() for consumer in consumers}
    return DownstreamUsedSummary(
        epoch0=epoch0_path,
        promoted=len(promoted_by_fqn),
        used=len(consumers_by_promoted),
        consumers=len(consumer_names),
        probe_unknown=probe_unknown,
    )
