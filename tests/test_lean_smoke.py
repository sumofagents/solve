from pathlib import Path

import pytest

from solve.lean.replay import replay_file, write_smoke_module

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.lean
def test_generated_epoch0_replays_under_lake():
    target = write_smoke_module(ROOT / "lean" / "Solve" / "Generated" / "Epoch0.lean")
    result = replay_file(target, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sorryAx" not in result.stdout + result.stderr
