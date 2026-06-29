from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from solve.lean.term_inspect import (
    parse_structural_output,
    probe_structural_packaging,
    probe_structural_packaging_details,
)


ROOT = Path(__file__).resolve().parents[1]


def _fake_runner(stdout: str, *, returncode: int = 0, timeout: bool = False, seen_cmd: list[list[str]] | None = None):
    def run(cmd: list[str], repo: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
        del repo, timeout_seconds
        if seen_cmd is not None:
            seen_cmd.append(cmd)
        if timeout:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)
        return subprocess.CompletedProcess(args=cmd, returncode=returncode, stdout=stdout, stderr="")

    return run


def test_structural_parser_reads_head_args_and_reason():
    result = parse_structural_output(
        'STRUCT {"target":"Solve.Generated.RunControl.t","head":"And.intro",'
        '"args":[{"kind":"const","name":"Nat.add_comm","imported":true}],'
        '"verdict":"structural","reason":"And.intro of imported atoms"}\n'
        "STRUCT_DONE\n"
    )

    assert result.target == "Solve.Generated.RunControl.t"
    assert result.head == "And.intro"
    assert result.args[0].kind == "const"
    assert result.args[0].name == "Nat.add_comm"
    assert result.args[0].imported is True
    assert result.reason == "And.intro of imported atoms"
    assert result.structural_packaging is True


def test_structural_parser_rejects_missing_done():
    with pytest.raises(RuntimeError, match="STRUCT_DONE"):
        parse_structural_output(
            'STRUCT {"target":"t","head":null,"args":[],"verdict":"error","reason":"bad"}\n'
        )


def test_structural_timeout_is_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setattr("solve.lean.term_inspect.find_tool", lambda name: name)

    structural, reason = probe_structural_packaging(
        "Solve.Generated.RunControl.t",
        repo=tmp_path,
        imports=["Solve.Generated.RunControl_test"],
        timeout=3,
        runner=_fake_runner("", timeout=True),
    )

    assert structural is False
    assert reason.startswith("probe_error:")


def test_structural_probe_threads_target_option(monkeypatch, tmp_path):
    monkeypatch.setattr("solve.lean.term_inspect.find_tool", lambda name: name)
    seen_cmd: list[list[str]] = []

    result = probe_structural_packaging_details(
        "Solve.Generated.RunControl.t",
        repo=tmp_path,
        imports=["Solve.Generated.RunControl_test"],
        timeout=3,
        runner=_fake_runner(
            'STRUCT {"target":"Solve.Generated.RunControl.t","head":"And.intro","args":[],'
            '"verdict":"structural","reason":"And.intro of imported atoms"}\nSTRUCT_DONE\n',
            seen_cmd=seen_cmd,
        ),
    )

    assert result.structural_packaging is True
    assert "-Dweak.solve.probe.target=Solve.Generated.RunControl.t" in seen_cmd[0]


@pytest.mark.lean
def test_real_structural_probe_detects_and_intro(tmp_path):
    module_path = ROOT / "lean" / "Solve" / "Generated" / "RunControl_struct_pos.lean"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(
        "import Mathlib.Data.Nat.Basic\n\n"
        "namespace Solve.Generated.RunControl\n\n"
        "def struct_pos := And.intro (@Nat.zero_lt_one) (@Nat.succ_ne_zero)\n\n"
        "end Solve.Generated.RunControl\n",
        encoding="utf-8",
    )
    try:
        structural, reason = probe_structural_packaging(
            "Solve.Generated.RunControl.struct_pos",
            repo=ROOT,
            imports=["Solve.Generated.RunControl_struct_pos"],
            timeout=60,
        )
    finally:
        module_path.unlink(missing_ok=True)

    assert structural is True
    assert reason.startswith("And.intro")


@pytest.mark.lean
def test_real_structural_probe_rejects_applied_imported_head(tmp_path):
    """An argument like `Nat.succ_pos n` (application, not atom) must NOT be
    classified as structural packaging, even though its head is imported."""
    module_path = ROOT / "lean" / "Solve" / "Generated" / "RunControl_struct_app.lean"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(
        "import Mathlib.Data.Nat.Basic\n\n"
        "namespace Solve.Generated.RunControl\n\n"
        "def struct_app := And.intro (@Nat.zero_lt_one) (@Nat.add_comm 0)\n\n"
        "end Solve.Generated.RunControl\n",
        encoding="utf-8",
    )
    try:
        structural, reason = probe_structural_packaging(
            "Solve.Generated.RunControl.struct_app",
            repo=ROOT,
            imports=["Solve.Generated.RunControl_struct_app"],
            timeout=60,
        )
    finally:
        module_path.unlink(missing_ok=True)

    # The second arg (@Nat.add_comm 0) is an application of an imported
    # constant to an explicit argument, NOT a bare atom. Must be rejected.
    assert structural is False


@pytest.mark.lean
def test_real_structural_probe_rejects_non_constructor_head(tmp_path):
    module_path = ROOT / "lean" / "Solve" / "Generated" / "RunControl_struct_neg.lean"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(
        "import Mathlib.Data.Nat.Basic\n\n"
        "namespace Solve.Generated.RunControl\n\n"
        "def struct_neg := @Nat.add_comm\n\n"
        "end Solve.Generated.RunControl\n",
        encoding="utf-8",
    )
    try:
        structural, reason = probe_structural_packaging(
            "Solve.Generated.RunControl.struct_neg",
            repo=ROOT,
            imports=["Solve.Generated.RunControl_struct_neg"],
            timeout=60,
        )
    finally:
        module_path.unlink(missing_ok=True)

    assert structural is False
    assert "non-structural" in reason
