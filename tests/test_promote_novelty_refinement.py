from __future__ import annotations

import hashlib
import json

import pytest

from solve.lean.codegen import write_run_control_module
from solve.lean.replay import build_modules, replay_file
from solve.lean.value import classify_value
from solve.promote import promote
from solve.verify.candidates import GeneratedCandidate, make_candidate_id
from solve.verify.receipts import CandidateReceipt, ReplayResult, write_jsonl

from phase5a_helpers import (
    DEFAULT_PARENTS,
    DEFAULT_PROOF_TERM,
    DEFAULT_STATEMENT,
    ROOT,
    cleanup_generated_for,
    promoted_classified_row,
    promoted_module_name,
    source_module_name,
    write_jsonl_dicts,
    write_phase5a_spec,
    write_source_run_control_module,
)


@pytest.mark.lean
def test_promoted_prefix_makes_restatement_existing_defeq_duplicate(tmp_path):
    spec_name = "phase5a-novelty"
    cleanup_generated_for(spec_name)
    try:
        spec_path, spec = write_phase5a_spec(
            tmp_path,
            spec_name,
            namespace_prefixes=["Phase5aNoImportedMatch"],
        )
        write_source_run_control_module(spec)
        build_modules(ROOT, [source_module_name(spec)], timeout=300)
        classified_path = write_jsonl_dicts(
            tmp_path / "value_classified.jsonl",
            [promoted_classified_row(spec)],
        )
        promote(
            spec_path,
            repo=ROOT,
            classified_path=classified_path,
            out_promoted=tmp_path / "promoted.jsonl",
            metrics_path=tmp_path / "promotion_metrics.json",
            timeout=300,
        )

        candidate = GeneratedCandidate(
            candidate_id=make_candidate_id("And.intro", DEFAULT_PARENTS, 1),
            operator="And.intro",
            parents=DEFAULT_PARENTS,
            depth=1,
            generated_theorem_name="Solve.Generated.RunControl.solve_generated_epoch1_0",
            parent_atom_kinds=("theorem", "theorem"),
        )
        epoch1_module = write_run_control_module(
            [candidate],
            repo=ROOT,
            spec=spec,
            module_suffix=f"{spec.name}_epoch1",
            extra_imports=[promoted_module_name(spec)],
        )
        replay = replay_file(epoch1_module, cwd=ROOT, timeout=300)
        assert replay.returncode == 0
        assert "sorryAx" not in replay.stdout
        assert "sorryAx" not in replay.stderr

        statement_hash = "sha256:" + hashlib.sha256(DEFAULT_STATEMENT.encode("utf-8")).hexdigest()
        receipt = CandidateReceipt(
            record_id="cand_phase5a_epoch1_restate",
            experiment_id=spec.name,
            toolchain=spec.lean.toolchain,
            imports=list(spec.lean.imports),
            statement=DEFAULT_STATEMENT,
            proof_term=DEFAULT_PROOF_TERM,
            generated_theorem_name=candidate.generated_theorem_name,
            parents=list(DEFAULT_PARENTS),
            operator="And.intro",
            depth=1,
            normalized_statement_hash=statement_hash,
            axioms_used=[],
            replay=ReplayResult(
                command=[str(part) for part in replay.args],
                exit_code=replay.returncode,
                stdout=replay.stdout or "",
                stderr=replay.stderr or "",
            ),
            interestingness_classification="trivial",
            epoch=1,
        )
        receipts_path = write_jsonl(tmp_path / "epoch1_receipts.jsonl", [receipt])

        classify_value(
            spec_path,
            repo=ROOT,
            receipts_path=receipts_path,
            out_path=tmp_path / "value_without_promoted.jsonl",
            metrics_path=tmp_path / "metrics_without_promoted.json",
            novelty_candidate_cap=5_000,
            novelty_timeout_seconds=60,
            max_receipts=1,
        )
        without_promoted = json.loads((tmp_path / "value_without_promoted.jsonl").read_text(encoding="utf-8"))
        assert without_promoted["novelty_classification"] == "novel_in_imported_env"

        classify_value(
            spec_path,
            repo=ROOT,
            receipts_path=receipts_path,
            out_path=tmp_path / "value_with_promoted.jsonl",
            metrics_path=tmp_path / "metrics_with_promoted.json",
            novelty_candidate_cap=5_000,
            novelty_timeout_seconds=60,
            promoted_prefixes=[promoted_module_name(spec)],
            max_receipts=1,
        )
        with_promoted = json.loads((tmp_path / "value_with_promoted.jsonl").read_text(encoding="utf-8"))
        expected_witness = f"{promoted_module_name(spec)}.solve_generated_0"
        assert with_promoted["novelty_classification"] == "existing_defeq_duplicate"
        assert with_promoted["novelty_witness"] == expected_witness
    finally:
        cleanup_generated_for(spec_name)
