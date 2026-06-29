from __future__ import annotations

import os
import subprocess
import sys

from phase5a_helpers import ROOT


def _run_help(tmp_path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPYCACHEPREFIX": str(tmp_path / "pycache")}
    return subprocess.run(
        [sys.executable, "-m", "solve", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
    )


def test_promote_help_exits_zero(tmp_path):
    result = _run_help(tmp_path, "promote", "--help")

    assert result.returncode == 0
    assert "--classified" in result.stdout
    assert "--out" in result.stdout


def test_run_control_help_mentions_epoch_extension(tmp_path):
    result = _run_help(tmp_path, "run-control", "--help")

    assert result.returncode == 0
    assert "--epoch" in result.stdout
    assert "--extend-with" in result.stdout
