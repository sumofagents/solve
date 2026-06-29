"""Lean replay helpers.

These helpers execute real Lean/Lake commands. They do not interpret language-model
outputs as proofs.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SMOKE_MODULE = '''namespace Solve.Generated

theorem smoke_replay : 1 + 1 = 2 := by
  rfl

#print axioms Solve.Generated.smoke_replay

end Solve.Generated
'''


def find_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    fallback = Path.home() / ".elan" / "bin" / name
    if fallback.exists():
        return str(fallback)
    raise FileNotFoundError(f"could not find {name!r} on PATH or under ~/.elan/bin")


def write_smoke_module(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SMOKE_MODULE, encoding="utf-8")
    return path


def replay_file(path: str | Path, cwd: str | Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    path = Path(path)
    cwd_path = Path(cwd) if cwd is not None else Path.cwd()
    lakefile = cwd_path / "lakefile.lean"
    if lakefile.exists():
        cmd = [find_tool("lake"), "env", "lean", str(path)]
    else:
        cmd = [find_tool("lean"), str(path)]
    return subprocess.run(cmd, cwd=cwd_path, text=True, capture_output=True, timeout=timeout)
