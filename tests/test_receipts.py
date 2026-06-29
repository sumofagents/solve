from solve.verify.receipts import CandidateReceipt, ReplayResult, read_jsonl, write_jsonl


def test_receipt_jsonl_roundtrip(tmp_path):
    receipt = CandidateReceipt(
        record_id="r0",
        experiment_id="run0-nat-control",
        toolchain="leanprover/lean4:v4.31.0",
        imports=["Mathlib.Data.Nat.Basic"],
        statement="1 + 1 = 2",
        proof_term="by rfl",
        generated_theorem_name="Solve.Generated.smoke_replay",
        parents=[],
        operator="Eq.refl",
        depth=0,
        normalized_statement_hash="sha256:test",
        axioms_used=[],
        replay=ReplayResult(command=["lake", "env", "lean", "lean/Solve/Generated/Epoch0.lean"], exit_code=0),
        novelty_classification="novel_in_imported_env",
        interestingness_classification="trivial",
    )
    path = write_jsonl(tmp_path / "receipts.jsonl", [receipt])
    loaded = read_jsonl(path)
    assert loaded == [receipt]
    assert loaded[0].replay_accepted is True


def test_sorry_ax_blocks_acceptance():
    result = ReplayResult(command=["lean", "bad.lean"], exit_code=0, stdout="depends on axioms: [sorryAx]")
    assert result.accepted is False
