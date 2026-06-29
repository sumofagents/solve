from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from solve.cli import build_parser
from solve.lean.replay import build_modules
from solve.lean.usage import UsageProbeResult
from solve.verify.promoted import PromotedAtomRecord, read_promoted_jsonl, write_promoted_jsonl
from solve.verify.receipts import CandidateReceipt, ReplayResult, read_jsonl, write_jsonl

from phase5a_helpers import ROOT, cleanup_generated_for, safe_suffix, write_phase5a_spec


def _promoted_module_name(spec_name: str) -> str:
    return f"Solve.Generated.Promoted_{safe_suffix(spec_name)}"


def _epoch1_module_name(spec_name: str) -> str:
    return f"Solve.Generated.RunControl_{safe_suffix(f'{spec_name}_epoch1')}"


def _write_spec_with_imports(tmp_path: Path, spec_name: str, imports: list[str]):
    spec_path, spec = write_phase5a_spec(tmp_path, spec_name)
    spec = spec.model_copy(update={"lean": spec.lean.model_copy(update={"imports": imports})})
    spec_path.write_text(yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    return spec_path, spec


def _receipt(
    *,
    spec,
    record_id: str,
    generated_theorem_name: str,
    epoch: int,
    proof_term: str = "True.intro",
    statement: str = "True",
    parents: list[str] | None = None,
    replay_exit_code: int = 0,
    replay_stdout: str = "",
) -> CandidateReceipt:
    return CandidateReceipt(
        record_id=record_id,
        experiment_id=spec.name,
        toolchain=spec.lean.toolchain,
        imports=list(spec.lean.imports),
        statement=statement,
        proof_term=proof_term,
        generated_theorem_name=generated_theorem_name,
        parents=list(parents or []),
        operator="And.intro",
        depth=1,
        normalized_statement_hash="sha256:" + hashlib.sha256(statement.encode("utf-8")).hexdigest(),
        axioms_used=[],
        replay=ReplayResult(
            command=["lake", "env", "lean", f"lean/Solve/Generated/RunControl_{safe_suffix(spec.name)}.lean"],
            exit_code=replay_exit_code,
            stdout=replay_stdout,
        ),
        structural_packaging=False,
        ingredient_trivial_by_automation=False,
        from_scratch_closure="not_closed",
        novelty_classification="novel_in_imported_env",
        promotable=True,
        interestingness_classification="unknown",
        epoch=epoch,
    )


def _promoted_record(*, spec, source_record_id: str, source_name: str, local_name: str = "atom_a") -> PromotedAtomRecord:
    promoted_module = _promoted_module_name(spec.name)
    return PromotedAtomRecord(
        record_id=f"promoted_{source_record_id}",
        experiment_id=spec.name,
        toolchain=spec.lean.toolchain,
        imports=list(spec.lean.imports),
        source_module="Solve.Generated.RunControl",
        source_record_id=source_record_id,
        source_generated_theorem_name=source_name,
        statement="True",
        proof_term="True.intro",
        promoted_module=promoted_module,
        local_name=local_name,
        fully_qualified_name=f"{promoted_module}.{local_name}",
        promoted=True,
        epoch=1,
        promoted_at_iso="2026-06-29T00:00:00Z",
    )


def _write_lean_usage_fixture(spec_name: str, consumer_locals: list[str]) -> tuple[str, str, str, list[str]]:
    promoted_module = _promoted_module_name(spec_name)
    epoch1_module = _epoch1_module_name(spec_name)
    atom_fqn = f"{promoted_module}.atom_a"
    generated = ROOT / "lean" / "Solve" / "Generated"
    generated.mkdir(parents=True, exist_ok=True)
    (generated / f"Promoted_{safe_suffix(spec_name)}.lean").write_text(
        f"namespace Solve.Generated.Promoted_{safe_suffix(spec_name)}\n\n"
        "def atom_a : True := True.intro\n\n"
        f"end Solve.Generated.Promoted_{safe_suffix(spec_name)}\n",
        encoding="utf-8",
    )
    theorem_blocks = []
    consumer_fqns = []
    for local in consumer_locals:
        consumer_fqns.append(f"Solve.Generated.RunControl.{local}")
        theorem_blocks.append(
            f"def {local} : True ∧ True :=\n"
            f"  And.intro {atom_fqn} {atom_fqn}\n\n"
            f"#print axioms Solve.Generated.RunControl.{local}"
        )
    (generated / f"RunControl_{safe_suffix(f'{spec_name}_epoch1')}.lean").write_text(
        f"import {promoted_module}\n\n"
        "namespace Solve.Generated.RunControl\n\n"
        + "\n\n".join(theorem_blocks)
        + "\n\nend Solve.Generated.RunControl\n",
        encoding="utf-8",
    )
    build_modules(ROOT, [promoted_module, epoch1_module, "Solve.Tools.UsageProbe"], timeout=300)
    return promoted_module, epoch1_module, atom_fqn, consumer_fqns


def _run_mark(
    spec_path: Path,
    *,
    epoch0_receipts: Path,
    epoch1_receipts: Path,
    promoted: Path,
    timeout: int = 60,
) -> int:
    parser = build_parser()
    args = parser.parse_args(
        [
            "mark-downstream-used",
            str(spec_path),
            "--epoch0-receipts",
            str(epoch0_receipts),
            "--epoch1-receipts",
            str(epoch1_receipts),
            "--promoted",
            str(promoted),
            "--repo",
            str(ROOT),
            "--timeout",
            str(timeout),
        ]
    )
    return int(args.func(args))


def _write_basic_files(tmp_path: Path, spec, atom_fqn: str, consumer_names: list[str], *, retained: bool = True):
    source_name = "Solve.Generated.RunControl.source_atom_a"
    atom_receipt = _receipt(spec=spec, record_id="epoch0_atom_a", generated_theorem_name=source_name, epoch=0)
    other_receipt = _receipt(
        spec=spec,
        record_id="epoch0_other",
        generated_theorem_name="Solve.Generated.RunControl.source_other",
        epoch=0,
    )
    epoch0_path = write_jsonl(tmp_path / "epoch0_receipts.jsonl", [atom_receipt, other_receipt])
    proof_term = f"And.intro {atom_fqn} {atom_fqn}"
    epoch1 = [
        _receipt(
            spec=spec,
            record_id=f"epoch1_{index}",
            generated_theorem_name=name,
            epoch=1,
            proof_term=proof_term,
            statement="True ∧ True",
            replay_exit_code=0 if retained else 1,
        )
        for index, name in enumerate(consumer_names)
    ]
    epoch1_path = write_jsonl(tmp_path / "epoch1_receipts.jsonl", epoch1)
    promoted_path = write_promoted_jsonl(
        tmp_path / "promoted.jsonl",
        [_promoted_record(spec=spec, source_record_id=atom_receipt.record_id, source_name=source_name)],
    )
    return epoch0_path, epoch1_path, promoted_path, atom_receipt, other_receipt


@pytest.mark.lean
def test_mark_downstream_used_happy_path(tmp_path):
    spec_name = "phase5b-downstream-happy"
    cleanup_generated_for(spec_name)
    try:
        _promoted_module, epoch1_module, atom_fqn, consumers = _write_lean_usage_fixture(
            spec_name,
            [f"consumer_{safe_suffix(spec_name)}"],
        )
        spec_path, spec = _write_spec_with_imports(tmp_path, spec_name, [epoch1_module])
        epoch0_path, epoch1_path, promoted_path, _atom_receipt, other_receipt = _write_basic_files(
            tmp_path,
            spec,
            atom_fqn,
            consumers,
        )

        assert _run_mark(spec_path, epoch0_receipts=epoch0_path, epoch1_receipts=epoch1_path, promoted=promoted_path) == 0

        loaded = read_jsonl(epoch0_path)
        assert loaded[0].downstream_used is True
        assert loaded[0].downstream_used_by == [consumers[0]]
        assert loaded[1] == other_receipt
    finally:
        cleanup_generated_for(spec_name)


@pytest.mark.lean
def test_self_reference_filter_drops_only_promoted_parent(tmp_path):
    spec_name = "phase5b-downstream-self"
    cleanup_generated_for(spec_name)
    try:
        _promoted_module, epoch1_module, atom_fqn, consumers = _write_lean_usage_fixture(
            spec_name,
            [f"consumer_{safe_suffix(spec_name)}"],
        )
        spec_path, spec = _write_spec_with_imports(tmp_path, spec_name, [epoch1_module])
        epoch0_path, _epoch1_path, promoted_path, _atom_receipt, _other_receipt = _write_basic_files(
            tmp_path,
            spec,
            atom_fqn,
            consumers,
        )
        self_ref_receipt = _receipt(
            spec=spec,
            record_id="epoch1_self_ref",
            generated_theorem_name=consumers[0],
            epoch=1,
            proof_term=f"And.intro {atom_fqn} {atom_fqn}",
            statement="True ∧ True",
            parents=[atom_fqn],
        )
        epoch1_path = write_jsonl(tmp_path / "epoch1_receipts.jsonl", [self_ref_receipt])

        assert _run_mark(spec_path, epoch0_receipts=epoch0_path, epoch1_receipts=epoch1_path, promoted=promoted_path) == 0

        loaded = read_jsonl(epoch0_path)
        assert loaded[0].downstream_used is None
        assert loaded[0].downstream_used_by is None
    finally:
        cleanup_generated_for(spec_name)


@pytest.mark.lean
def test_non_retained_epoch1_is_ignored(tmp_path):
    spec_name = "phase5b-downstream-not-retained"
    cleanup_generated_for(spec_name)
    try:
        _promoted_module, epoch1_module, atom_fqn, consumers = _write_lean_usage_fixture(
            spec_name,
            [f"consumer_{safe_suffix(spec_name)}"],
        )
        spec_path, spec = _write_spec_with_imports(tmp_path, spec_name, [epoch1_module])
        epoch0_path, epoch1_path, promoted_path, _atom_receipt, _other_receipt = _write_basic_files(
            tmp_path,
            spec,
            atom_fqn,
            consumers,
            retained=False,
        )

        assert _run_mark(spec_path, epoch0_receipts=epoch0_path, epoch1_receipts=epoch1_path, promoted=promoted_path) == 0

        loaded = read_jsonl(epoch0_path)
        assert loaded[0].downstream_used is None
        assert loaded[0].downstream_used_by is None
    finally:
        cleanup_generated_for(spec_name)


def test_probe_unknown_is_fail_closed(monkeypatch, tmp_path, capsys):
    spec_name = "phase5b-downstream-unknown"
    atom_fqn = f"{_promoted_module_name(spec_name)}.atom_a"
    spec_path, spec = _write_spec_with_imports(tmp_path, spec_name, ["Solve.Generated.RunControl_fake"])
    epoch0_path, epoch1_path, promoted_path, _atom_receipt, _other_receipt = _write_basic_files(
        tmp_path,
        spec,
        atom_fqn,
        ["Solve.Generated.RunControl.consumer_unknown"],
    )

    def fake_probe(target_name: str, **_kwargs) -> UsageProbeResult:
        return UsageProbeResult(target=target_name, used_promoted=(), unknown=True, reason="probe_error: timeout")

    monkeypatch.setattr("solve.lean.downstream.probe_usage", fake_probe)

    assert _run_mark(spec_path, epoch0_receipts=epoch0_path, epoch1_receipts=epoch1_path, promoted=promoted_path) == 0

    loaded = read_jsonl(epoch0_path)
    captured = capsys.readouterr()
    assert loaded[0].downstream_used is None
    assert loaded[0].downstream_used_by is None
    assert "DOWNSTREAM_USED_PROBE_UNKNOWN" in captured.err


def test_atomic_rewrite_leaves_original_when_replace_fails(monkeypatch, tmp_path):
    spec_name = "phase5b-downstream-atomic"
    atom_fqn = f"{_promoted_module_name(spec_name)}.atom_a"
    spec_path, spec = _write_spec_with_imports(tmp_path, spec_name, ["Solve.Generated.RunControl_fake"])
    epoch0_path, epoch1_path, promoted_path, _atom_receipt, _other_receipt = _write_basic_files(
        tmp_path,
        spec,
        atom_fqn,
        ["Solve.Generated.RunControl.consumer_atomic"],
    )
    original = epoch0_path.read_bytes()

    def fake_probe(target_name: str, **_kwargs) -> UsageProbeResult:
        return UsageProbeResult(target=target_name, used_promoted=(atom_fqn,), unknown=False, reason="")

    with monkeypatch.context() as patch:
        patch.setattr("solve.lean.downstream.probe_usage", fake_probe)
        patch.setattr(
            "solve.lean.downstream.os.replace",
            lambda _src, _dst: (_ for _ in ()).throw(OSError("replace failed")),
        )
        assert _run_mark(spec_path, epoch0_receipts=epoch0_path, epoch1_receipts=epoch1_path, promoted=promoted_path) == 1

    assert epoch0_path.read_bytes() == original
    monkeypatch.setattr("solve.lean.downstream.probe_usage", fake_probe)
    assert _run_mark(spec_path, epoch0_receipts=epoch0_path, epoch1_receipts=epoch1_path, promoted=promoted_path) == 0
    assert read_jsonl(epoch0_path)[0].downstream_used is True


def test_downstream_used_by_schema_roundtrip_and_extra_forbid():
    receipt = CandidateReceipt(
        record_id="r0",
        experiment_id="run0-nat-control",
        toolchain="leanprover/lean4:v4.31.0",
        imports=["Mathlib.Data.Nat.Basic"],
        statement="True",
        proof_term="True.intro",
        generated_theorem_name="Solve.Generated.RunControl.source",
        parents=[],
        operator="True.intro",
        depth=0,
        normalized_statement_hash="sha256:test",
        axioms_used=[],
        replay=ReplayResult(command=["lake", "env", "lean", "run.lean"], exit_code=0),
        downstream_used=True,
        downstream_used_by=["Solve.Foo.bar", "Solve.Foo.baz"],
    )
    payload = json.dumps(receipt.model_dump(mode="json"))

    assert CandidateReceipt.model_validate_json(payload) == receipt
    with pytest.raises(Exception):
        CandidateReceipt.model_validate({**receipt.model_dump(mode="json"), "extra_field": "reject"})


@pytest.mark.lean
def test_multi_consumer_aggregation_is_sorted_and_deduped(tmp_path):
    spec_name = "phase5b-downstream-multi"
    cleanup_generated_for(spec_name)
    try:
        _promoted_module, epoch1_module, atom_fqn, consumers = _write_lean_usage_fixture(
            spec_name,
            [f"z_consumer_{safe_suffix(spec_name)}", f"a_consumer_{safe_suffix(spec_name)}"],
        )
        spec_path, spec = _write_spec_with_imports(tmp_path, spec_name, [epoch1_module])
        epoch0_path, epoch1_path, promoted_path, _atom_receipt, _other_receipt = _write_basic_files(
            tmp_path,
            spec,
            atom_fqn,
            consumers,
        )

        assert _run_mark(spec_path, epoch0_receipts=epoch0_path, epoch1_receipts=epoch1_path, promoted=promoted_path) == 0

        loaded = read_jsonl(epoch0_path)
        assert loaded[0].downstream_used is True
        assert loaded[0].downstream_used_by == sorted(consumers)
    finally:
        cleanup_generated_for(spec_name)


def test_real_run0_shape_spot_check(tmp_path):
    search_roots = [ROOT / "runs", ROOT / "examples"]
    receipt_paths = [
        path
        for root in search_roots
        if root.exists()
        for path in root.rglob("*epoch0*receipts*.jsonl")
    ]
    promoted_paths = [
        path
        for root in search_roots
        if root.exists()
        for path in root.rglob("*promoted*.jsonl")
    ]
    if not receipt_paths or not promoted_paths:
        pytest.skip("no real epoch0 receipts/promoted JSONL found under runs/ or examples/")

    try:
        real_receipts = read_jsonl(receipt_paths[0])
        real_promoted = read_promoted_jsonl(promoted_paths[0])
    except Exception as exc:
        pytest.skip(f"real fixture shape could not be loaded: {exc}")
    if not real_receipts or not real_promoted:
        pytest.skip("real receipt/promoted JSONL fixture is empty")

    spec_path, spec = _write_spec_with_imports(tmp_path, "phase5b-downstream-shape", ["Solve.Generated.Shape"])
    del spec_path
    synthetic_receipt = _receipt(
        spec=spec,
        record_id="shape_epoch0",
        generated_theorem_name="Solve.Generated.RunControl.shape",
        epoch=0,
    )
    synthetic_promoted = _promoted_record(
        spec=spec,
        source_record_id=synthetic_receipt.record_id,
        source_name=synthetic_receipt.generated_theorem_name,
    )

    assert set(synthetic_receipt.model_dump(mode="json")) == set(real_receipts[0].model_dump(mode="json"))
    assert set(synthetic_promoted.model_dump(mode="json")) == set(real_promoted[0].model_dump(mode="json"))
