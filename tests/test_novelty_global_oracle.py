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
        "theorem novelty_global_utf8_dup : ByteArray.empty = [].utf8Encode :=\n"
        "  Eq.symm List.utf8Encode_nil\n\n"
        "end Solve.Generated.RunControl\n",
        encoding="utf-8",
    )
    return module_path


@pytest.mark.lean
def test_brute_imported_finds_utf8_duplicate():
    """Oracle: brute-force scan against the imported List namespace finds the
    defeq duplicate of the Eq.symm candidate. This is the ground-truth check
    that proves the duplicate is detectable when scanning exhaustively."""
    module_path = _write_utf8_duplicate_module()
    try:
        results = probe_novelty_batch(
            ["Solve.Generated.RunControl.novelty_global_utf8_dup"],
            repo=ROOT,
            imports=["Solve.Generated.RunControl_novelty_global_utf8"],
            prefixes=["List"],
            scope="imported",
            verify_mode="brute",
            candidate_cap=10_000,
            timeout=300,
        )
    finally:
        module_path.unlink(missing_ok=True)

    assert results["Solve.Generated.RunControl.novelty_global_utf8_dup"].classification == "existing_defeq_duplicate"


@pytest.mark.lean
def test_brute_global_finds_utf8_duplicate():
    """Regression for Phase 6B hardening: global brute scope must include core
    library modules (Init/Std/Lean) as well as Mathlib modules. The witness for
    this duplicate may live in Init, not under a Mathlib.* module name."""
    module_path = _write_utf8_duplicate_module()
    try:
        results = probe_novelty_batch(
            ["Solve.Generated.RunControl.novelty_global_utf8_dup"],
            repo=ROOT,
            imports=["Solve.Generated.RunControl_novelty_global_utf8"],
            prefixes=["List"],
            scope="global",
            verify_mode="brute",
            candidate_cap=600_000,
            timeout=900,
            heartbeat_budget=2_000_000,
        )
    finally:
        module_path.unlink(missing_ok=True)

    result = results["Solve.Generated.RunControl.novelty_global_utf8_dup"]
    assert result.classification == "existing_defeq_duplicate"
    assert result.witness is not None
    assert not result.cap_hit


@pytest.mark.lean
@pytest.mark.xfail(
    reason="DiscrTree pre-filter can miss defeq matches that require Eq.symm "
           "(symmetric equalities are not grouped by DiscrTree.mkPath under "
           "reducible transparency). The brute-force oracle catches these; "
           "DiscrTree is a performance optimization that may need symmetric-variant "
           "querying to be sound. Tracked for future hardening."
)
def test_discrtree_imported_finds_utf8_duplicate():
    """Known limitation: DiscrTree narrowing does not group symmetric equalities.
    A candidate whose type is `b = a` (from Eq.symm) will not match against an
    imported theorem `a = b` in the DiscrTree, even though they are defeq.
    This test documents the limitation (xfail) until the DiscrTree query includes
    symmetric variants."""
    module_path = _write_utf8_duplicate_module()
    try:
        results = probe_novelty_batch(
            ["Solve.Generated.RunControl.novelty_global_utf8_dup"],
            repo=ROOT,
            imports=["Solve.Generated.RunControl_novelty_global_utf8"],
            prefixes=["List"],
            scope="imported",
            verify_mode="discrtree",
            candidate_cap=10_000,
            timeout=300,
        )
    finally:
        module_path.unlink(missing_ok=True)

    assert results["Solve.Generated.RunControl.novelty_global_utf8_dup"].classification == "existing_defeq_duplicate"
