import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.lean
def test_check_imports_run0_end_to_end():
    result = subprocess.run(
        [sys.executable, "-m", "solve.cli", "check-imports", "experiments/run0_nat_control.yaml"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "IMPORTS_OK experiments/run0_nat_control.yaml" in result.stdout
