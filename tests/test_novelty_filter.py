from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from solve.lean.novelty import parse_novelty_output, probe_novelty


ROOT = Path(__file__).resolve().parents[1]


def _fake_runner(stdout: str, *, timeout: bool = False, seen_cmd: list[list[str]] | None = None):
    def run(cmd: list[str], repo: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
        del repo, timeout_seconds
        if seen_cmd is not None:
            seen_cmd.append(cmd)
        if timeout:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=stdout, stderr="")

    return run


def test_novelty_parser_reads_duplicate_verdict():
    result = parse_novelty_output(
        'NOV {"target":"Solve.Generated.RunControl.t","verdict":"existing_defeq_duplicate",'
        '"witness":"Nat.add_comm","compared":12,"cap_hit":false,"reason":"defeq"}\n'
        "NOV_DONE\n"
    )

    assert result.classification == "existing_defeq_duplicate"
    assert result.witness == "Nat.add_comm"
    assert result.compared == 12
    assert result.cap_hit is False


def test_novelty_parser_reads_novel_verdict():
    result = parse_novelty_output(
        'NOV {"target":"Solve.Generated.RunControl.t","verdict":"novel_in_imported_env",'
        '"witness":null,"compared":500,"cap_hit":true,"reason":"none"}\n'
        "NOV_DONE\n"
    )

    assert result.classification == "novel_in_imported_env"
    assert result.witness is None
    assert result.cap_hit is True


def test_novelty_missing_done_and_timeout_are_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr("solve.lean.novelty.find_tool", lambda name: name)

    missing_done = probe_novelty(
        "Solve.Generated.RunControl.t",
        repo=tmp_path,
        imports=["Solve.Generated.RunControl_test"],
        prefixes=["Nat"],
        candidate_cap=17,
        timeout=3,
        runner=_fake_runner(
            'NOV {"target":"t","verdict":"novel_in_imported_env","witness":null,'
            '"compared":0,"cap_hit":false,"reason":"none"}\n'
        ),
    )
    timed_out = probe_novelty(
        "Solve.Generated.RunControl.t",
        repo=tmp_path,
        imports=["Solve.Generated.RunControl_test"],
        prefixes=["Nat"],
        candidate_cap=17,
        timeout=3,
        runner=_fake_runner("", timeout=True),
    )

    assert missing_done.classification == "unknown"
    assert missing_done.reason.startswith("probe_error:")
    assert timed_out.classification == "unknown"
    assert timed_out.reason.startswith("probe_error:")


def test_novelty_probe_threads_candidate_cap(monkeypatch, tmp_path):
    monkeypatch.setattr("solve.lean.novelty.find_tool", lambda name: name)
    seen_cmd: list[list[str]] = []

    result = probe_novelty(
        "Solve.Generated.RunControl.t",
        repo=tmp_path,
        imports=["Solve.Generated.RunControl_test"],
        prefixes=["Nat"],
        candidate_cap=23,
        timeout=3,
        runner=_fake_runner(
            'NOV {"target":"Solve.Generated.RunControl.t","verdict":"novel_in_imported_env",'
            '"witness":null,"compared":23,"cap_hit":false,"reason":"none"}\nNOV_DONE\n',
            seen_cmd=seen_cmd,
        ),
    )

    assert result.classification == "novel_in_imported_env"
    assert "-Dweak.solve.novelty.candidateCap=23" in seen_cmd[0]


@pytest.mark.lean
def test_real_novelty_probe_finds_nat_add_comm_duplicate(tmp_path):
    module_path = ROOT / "lean" / "Solve" / "Generated" / "RunControl_novelty_dup.lean"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(
        "import Mathlib.Data.Nat.Basic\n\n"
        "namespace Solve.Generated.RunControl\n\n"
        "def novelty_dup := @Nat.add_comm\n\n"
        "end Solve.Generated.RunControl\n",
        encoding="utf-8",
    )
    try:
        result = probe_novelty(
            "Solve.Generated.RunControl.novelty_dup",
            repo=ROOT,
            imports=["Solve.Generated.RunControl_novelty_dup"],
            prefixes=["Nat"],
            candidate_cap=5_000,
            timeout=60,
        )
    finally:
        module_path.unlink(missing_ok=True)

    assert result.classification == "existing_defeq_duplicate"
    assert result.witness == "Nat.add_comm"


@pytest.mark.lean
def test_real_novelty_probe_accepts_novel_conjunction(tmp_path):
    module_path = ROOT / "lean" / "Solve" / "Generated" / "RunControl_novelty_new.lean"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(
        "import Mathlib.Data.Nat.Basic\n\n"
        "namespace Solve.Generated.RunControl\n\n"
        "def novelty_new := And.intro (@Nat.add_comm) (@Nat.zero_lt_one)\n\n"
        "end Solve.Generated.RunControl\n",
        encoding="utf-8",
    )
    try:
        result = probe_novelty(
            "Solve.Generated.RunControl.novelty_new",
            repo=ROOT,
            imports=["Solve.Generated.RunControl_novelty_new"],
            prefixes=["Nat"],
            candidate_cap=5_000,
            timeout=60,
        )
    finally:
        module_path.unlink(missing_ok=True)

    assert result.classification == "novel_in_imported_env"
