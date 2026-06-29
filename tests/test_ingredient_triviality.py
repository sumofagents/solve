from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from solve.experiments.spec import load_experiment_spec
from solve.lean.triviality import AutomationBounds, classify_ingredient_triviality
from solve.verify.receipts import CandidateReceipt, ReplayResult


ROOT = Path(__file__).resolve().parents[1]


def _receipt(statement: str, *, parents: list[str] | None = None) -> tuple[dict[str, object], CandidateReceipt]:
    receipt = CandidateReceipt(
        record_id="cand_ingredient",
        experiment_id="run0-nat-control",
        toolchain="leanprover/lean4:v4.31.0",
        imports=["Mathlib.Data.Nat.Basic"],
        statement=statement,
        proof_term="by exact And.intro",
        generated_theorem_name="Solve.Generated.RunControl.solve_generated_ingredient",
        parents=parents if parents is not None else ["Nat.add_comm", "Nat.zero_lt_one"],
        operator="And.intro",
        depth=1,
        normalized_statement_hash="sha256:ingredient",
        axioms_used=[],
        replay=ReplayResult(command=["lake", "env", "lean", "run.lean"], exit_code=0),
        novelty_classification="unknown",
        interestingness_classification="trivial",
    )
    raw = receipt.model_dump(mode="json")
    raw.pop("ingredient_trivial_by_automation", None)
    raw.pop("ingredient_trivial_closed_by", None)
    return raw, receipt


def _tactic_from_module(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip().endswith(":= by") and index + 1 < len(lines):
            return lines[index + 1].strip()
    raise AssertionError("could not find tactic line")


def _fake_runner(*, closes_by: str | None = None, timeout_on: str | None = None, seen: list[str] | None = None):
    def run(path: Path, repo: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
        del repo, timeout_seconds
        tactic = _tactic_from_module(path)
        if seen is not None:
            seen.append(tactic)
        if tactic == timeout_on:
            raise subprocess.TimeoutExpired(cmd=["lake", "env", "lean", str(path)], timeout=1)
        return subprocess.CompletedProcess(
            args=["lake", "env", "lean", str(path)],
            returncode=0 if tactic == closes_by else 1,
            stdout="",
            stderr="" if tactic == closes_by else "unsolved goals",
        )

    return run


def _classify(
    tmp_path: Path,
    statement: str,
    *,
    parents: list[str] | None = None,
    closes_by: str | None = None,
    timeout_on: str | None = None,
    seen: list[str] | None = None,
) -> dict[str, object]:
    raw, receipt = _receipt(statement, parents=parents)
    return classify_ingredient_triviality(
        raw,
        receipt=receipt,
        spec=load_experiment_spec(ROOT / "experiments" / "run0_nat_control.yaml"),
        repo=ROOT,
        bounds=AutomationBounds(heartbeat_budget=100, step_budget=12, timeout_seconds=4),
        transient_dir=tmp_path,
        runner=_fake_runner(closes_by=closes_by, timeout_on=timeout_on, seen=seen),
    )


def test_ingredient_bouquet_formats_parent_templates_and_stops_at_first_close(tmp_path):
    tactic = "simp [Nat.add_comm, Nat.zero_lt_one]"
    seen: list[str] = []

    classified = _classify(tmp_path, "True ∧ True", closes_by=tactic, seen=seen)

    assert classified["ingredient_trivial_by_automation"] is True
    assert classified["ingredient_trivial_closed_by"] == tactic
    assert seen == [tactic]


def test_ingredient_bouquet_attempts_until_later_close(tmp_path):
    seen: list[str] = []

    classified = _classify(tmp_path, "True ∧ True", closes_by="omega", seen=seen)

    assert classified["ingredient_trivial_by_automation"] is True
    assert classified["ingredient_trivial_closed_by"] == "omega"
    assert seen == ["simp [Nat.add_comm, Nat.zero_lt_one]", "decide", "omega"]


def test_receipts_missing_two_parents_skip_parent_dependent_tactics(tmp_path):
    seen: list[str] = []

    classified = _classify(tmp_path, "True", parents=["Nat.add_comm"], closes_by="decide", seen=seen)

    assert classified["ingredient_trivial_by_automation"] is True
    assert classified["ingredient_trivial_closed_by"] == "decide"
    assert seen[0] == "decide"
    assert all("{" not in tactic for tactic in seen)


def test_ingredient_timeout_is_unknown_and_fail_closed(tmp_path):
    classified = _classify(
        tmp_path,
        "True ∧ True",
        timeout_on="simp [Nat.add_comm, Nat.zero_lt_one]",
    )

    assert classified["ingredient_trivial_by_automation"] is None
    assert classified["ingredient_trivial_closed_by"] is None


@pytest.mark.lean
def test_real_ingredient_classifier_closes_parent_conjunction(tmp_path):
    raw, receipt = _receipt("(∀ n m : Nat, n + m = m + n) ∧ 0 < 1")
    classified = classify_ingredient_triviality(
        raw,
        receipt=receipt,
        spec=load_experiment_spec(ROOT / "experiments" / "run0_nat_control.yaml"),
        repo=ROOT,
        bounds=AutomationBounds(heartbeat_budget=20_000, step_budget=1_000, timeout_seconds=30),
        transient_dir=tmp_path,
    )

    assert json.dumps(classified)
    assert classified["ingredient_trivial_by_automation"] is True
    assert classified["ingredient_trivial_closed_by"] is not None
