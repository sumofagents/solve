from __future__ import annotations

from pathlib import Path

import pytest

from solve.lean.novelty import probe_novelty_batch


ROOT = Path(__file__).resolve().parents[1]


def _write_utf8_duplicate_module() -> Path:
    module_path = ROOT / "lean" / "Solve" / "Generated" / "RunControl_novelty_global_utf8.lean"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(
        "import Mathlib\n\n"
        "namespace Solve.Generated.RunControl\n\n"
        "def novelty_global_utf8_dup := @Eq.symm _ _ _ List.utf8Encode_nil\n\n"
        "end Solve.Generated.RunControl\n",
        encoding="utf-8",
    )
    return module_path


@pytest.mark.lean
def test_global_brute_finds_utf8_duplicate():
    module_path = _write_utf8_duplicate_module()
    try:
        results = probe_novelty_batch(
            ["Solve.Generated.RunControl.novelty_global_utf8_dup"],
            repo=ROOT,
            imports=["Solve.Generated.RunControl_novelty_global_utf8"],
            prefixes=["List"],
            scope="global",
            verify_mode="brute",
            candidate_cap=1_000_000,
            timeout=300,
        )
    finally:
        module_path.unlink(missing_ok=True)

    assert results["Solve.Generated.RunControl.novelty_global_utf8_dup"].classification == "existing_defeq_duplicate"


@pytest.mark.lean
def test_global_discrtree_finds_utf8_duplicate():
    module_path = _write_utf8_duplicate_module()
    try:
        results = probe_novelty_batch(
            ["Solve.Generated.RunControl.novelty_global_utf8_dup"],
            repo=ROOT,
            imports=["Solve.Generated.RunControl_novelty_global_utf8"],
            prefixes=["List"],
            scope="global",
            verify_mode="discrtree",
            candidate_cap=5_000,
            timeout=300,
        )
    finally:
        module_path.unlink(missing_ok=True)

    assert results["Solve.Generated.RunControl.novelty_global_utf8_dup"].classification == "existing_defeq_duplicate"
