from __future__ import annotations

import subprocess
from pathlib import Path

from solve.lean.novelty import parse_novelty_batch_output, probe_novelty_batch


def _fake_runner(
    stdout: str,
    *,
    stderr: str = "",
    returncode: int = 0,
    timeout: bool = False,
):
    def run(cmd: list[str], repo: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
        del repo, timeout_seconds
        if timeout:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)
        return subprocess.CompletedProcess(args=cmd, returncode=returncode, stdout=stdout, stderr=stderr)

    return run


def test_batch_parser_reads_nov_index_and_done():
    results = parse_novelty_batch_output(
        'NOV {"target":"A.t","verdict":"existing_defeq_duplicate","witness":"List.nil_eq",'
        '"compared":3,"cap_hit":false,"reason":"defeq","bucket_size":3,"index_size":10,"mode":"discrtree"}\n'
        'NOV {"target":"B.t","verdict":"novel_in_imported_env","witness":null,'
        '"compared":2,"cap_hit":false,"reason":"none","bucket_size":2,"index_size":10,"mode":"discrtree"}\n'
        'NOV_INDEX {"mode":"discrtree","global_scope":true,"index_size":10,"target_count":2}\n'
        "NOV_DONE\n",
        ["A.t", "B.t"],
    )

    assert results["A.t"].classification == "existing_defeq_duplicate"
    assert results["A.t"].witness == "List.nil_eq"
    assert results["B.t"].classification == "novel_in_imported_env"
    assert results["B.t"].compared == 2


def test_batch_probe_missing_target_is_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr("solve.lean.novelty.find_tool", lambda name: name)

    results = probe_novelty_batch(
        ["A.t", "B.t"],
        repo=tmp_path,
        imports=["Solve.Generated.RunControl_test"],
        prefixes=["List"],
        candidate_cap=17,
        timeout=3,
        runner=_fake_runner(
            'NOV {"target":"A.t","verdict":"novel_in_imported_env","witness":null,'
            '"compared":0,"cap_hit":false,"reason":"none"}\n'
            "NOV_DONE\n"
        ),
    )

    assert results["A.t"].classification == "novel_in_imported_env"
    assert results["B.t"].classification == "unknown"
    assert "missing NOV result" in results["B.t"].reason


def test_batch_probe_nonzero_returncode_marks_every_target_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr("solve.lean.novelty.find_tool", lambda name: name)

    results = probe_novelty_batch(
        ["A.t", "B.t"],
        repo=tmp_path,
        imports=["Solve.Generated.RunControl_test"],
        prefixes=["List"],
        candidate_cap=17,
        timeout=3,
        runner=_fake_runner("", stderr="lean failed", returncode=1),
    )

    assert {target: result.classification for target, result in results.items()} == {
        "A.t": "unknown",
        "B.t": "unknown",
    }
    assert all("lean failed" in result.reason for result in results.values())


def test_batch_probe_timeout_marks_every_target_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr("solve.lean.novelty.find_tool", lambda name: name)

    results = probe_novelty_batch(
        ["A.t", "B.t"],
        repo=tmp_path,
        imports=["Solve.Generated.RunControl_test"],
        prefixes=["List"],
        candidate_cap=17,
        timeout=3,
        runner=_fake_runner("", timeout=True),
    )

    assert all(result.classification == "unknown" for result in results.values())
    assert all(result.reason.startswith("probe_error: timeout after 3s") for result in results.values())
