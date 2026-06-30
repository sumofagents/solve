"""Tests for the Lean elaborated-proof-size probe."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from solve.lean.proof_size import (
    PROOFSIZE_DONE,
    PROOFSIZE_PREFIX,
    ProofSizeResult,
    parse_proof_size_output,
    probe_proof_size,
)


ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_MODULE_NAME = "Solve.Generated.ProofShorteningSynthetic"
SYNTHETIC_PATH = ROOT / "lean" / "Solve" / "Generated" / "ProofShorteningSynthetic.lean"


SYNTHETIC_SRC = """\
namespace Solve.Generated.ProofShorteningSynthetic

/-- Promoted-like helper. -/
theorem promoted_pair : True ∧ True := And.intro True.intro True.intro

/-- Baseline: build the conjunction directly, then wrap it in a let-binding so
    the elaborated proof Expr is strictly larger than the with-promoted version. -/
theorem without_pair : True ∧ True :=
  let p : True ∧ True := And.intro True.intro True.intro
  let q : True ∧ True := And.intro p.left p.right
  And.intro q.left q.right

/-- With-promoted: directly use the helper. -/
theorem with_pair : True ∧ True := promoted_pair

end Solve.Generated.ProofShorteningSynthetic
"""


def _write_synthetic_module() -> Path:
    SYNTHETIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SYNTHETIC_PATH.write_text(SYNTHETIC_SRC, encoding="utf-8")
    return SYNTHETIC_PATH


@pytest.fixture(scope="module")
def synthetic_module():
    path = _write_synthetic_module()
    try:
        yield SYNTHETIC_MODULE_NAME
    finally:
        path.unlink(missing_ok=True)


# ------------------------------------------------------------------ parser tests

def test_parser_reads_ok_payload():
    payload = (
        f'{PROOFSIZE_PREFIX}{{"target":"Foo.bar","verdict":"ok","term_size":7,'
        '"required_const":"Foo.helper","used_required_const":true,"reason":""}\n'
        f"{PROOFSIZE_DONE}\n"
    )
    result = parse_proof_size_output(payload)
    assert result == ProofSizeResult(
        target="Foo.bar",
        verdict="ok",
        term_size=7,
        required_const="Foo.helper",
        used_required_const=True,
        reason="",
    )


def test_parser_reads_unknown_payload_with_null_fields():
    payload = (
        f'{PROOFSIZE_PREFIX}{{"target":"Foo.bar","verdict":"unknown","term_size":null,'
        '"required_const":null,"used_required_const":null,"reason":"target not found"}\n'
        f"{PROOFSIZE_DONE}\n"
    )
    result = parse_proof_size_output(payload)
    assert result.verdict == "unknown"
    assert result.term_size is None
    assert result.required_const is None
    assert result.used_required_const is None
    assert result.reason == "target not found"


def test_parser_rejects_missing_done():
    bad = (
        f'{PROOFSIZE_PREFIX}{{"target":"Foo.bar","verdict":"ok","term_size":1,'
        '"required_const":null,"used_required_const":null,"reason":""}\n'
    )
    with pytest.raises(RuntimeError, match="PROOFSIZE_DONE"):
        parse_proof_size_output(bad)


def test_parser_rejects_multiple_proofsize_lines():
    bad = (
        f'{PROOFSIZE_PREFIX}{{"target":"Foo.bar","verdict":"ok","term_size":1,'
        '"required_const":null,"used_required_const":null,"reason":""}\n'
        f'{PROOFSIZE_PREFIX}{{"target":"Foo.baz","verdict":"ok","term_size":2,'
        '"required_const":null,"used_required_const":null,"reason":""}\n'
        f"{PROOFSIZE_DONE}\n"
    )
    with pytest.raises(RuntimeError, match="PROOFSIZE lines"):
        parse_proof_size_output(bad)


def test_parser_rejects_invalid_verdict():
    bad = (
        f'{PROOFSIZE_PREFIX}{{"target":"Foo.bar","verdict":"yes","term_size":1,'
        '"required_const":null,"used_required_const":null,"reason":""}\n'
        f"{PROOFSIZE_DONE}\n"
    )
    with pytest.raises(RuntimeError, match="verdict"):
        parse_proof_size_output(bad)


def test_parser_rejects_ok_payload_without_term_size():
    bad = (
        f'{PROOFSIZE_PREFIX}{{"target":"Foo.bar","verdict":"ok","term_size":null,'
        '"required_const":null,"used_required_const":null,"reason":""}\n'
        f"{PROOFSIZE_DONE}\n"
    )
    with pytest.raises(RuntimeError, match="term_size"):
        parse_proof_size_output(bad)


def test_parser_rejects_malformed_json():
    bad = f"{PROOFSIZE_PREFIX}{{not json}}\n{PROOFSIZE_DONE}\n"
    with pytest.raises(ValueError):
        parse_proof_size_output(bad)


def test_probe_runner_failure_returns_unknown(tmp_path):
    """When the lake runner non-zero-exits, probe must return unknown, not raise."""

    def fake_runner(_cmd, _cwd, _timeout):
        import subprocess

        return subprocess.CompletedProcess(
            args=_cmd, returncode=1, stdout="", stderr="lake exploded"
        )

    result = probe_proof_size(
        "Foo.bar",
        repo=tmp_path,
        imports=[],
        timeout=10,
        runner=fake_runner,
    )
    assert result.verdict == "unknown"
    assert result.term_size is None
    assert result.reason.startswith("probe_error:")


def test_probe_unparseable_output_returns_unknown(tmp_path):
    def fake_runner(_cmd, _cwd, _timeout):
        import subprocess

        return subprocess.CompletedProcess(
            args=_cmd, returncode=0, stdout="garbage with no PROOFSIZE line\n", stderr=""
        )

    result = probe_proof_size(
        "Foo.bar",
        repo=tmp_path,
        imports=[],
        timeout=10,
        runner=fake_runner,
    )
    assert result.verdict == "unknown"
    assert result.term_size is None
    assert "probe_error" in result.reason


# ------------------------------------------------------------------ real Lean tests

@pytest.mark.lean
def test_probe_real_synthetic_target_is_ok_with_positive_term_size(synthetic_module):
    result = probe_proof_size(
        f"{synthetic_module}.promoted_pair",
        repo=ROOT,
        imports=[synthetic_module],
        timeout=120,
    )
    assert result.verdict == "ok", result.reason
    assert isinstance(result.term_size, int)
    assert result.term_size > 0
    # No required const requested.
    assert result.required_const is None
    assert result.used_required_const is None


@pytest.mark.lean
def test_probe_required_const_detection_with_promoted(synthetic_module):
    required = f"{synthetic_module}.promoted_pair"
    result = probe_proof_size(
        f"{synthetic_module}.with_pair",
        repo=ROOT,
        imports=[synthetic_module],
        required_const=required,
        timeout=120,
    )
    assert result.verdict == "ok", result.reason
    assert result.required_const == required
    assert result.used_required_const is True


@pytest.mark.lean
def test_probe_required_const_absent_in_baseline(synthetic_module):
    required = f"{synthetic_module}.promoted_pair"
    result = probe_proof_size(
        f"{synthetic_module}.without_pair",
        repo=ROOT,
        imports=[synthetic_module],
        required_const=required,
        timeout=120,
    )
    assert result.verdict == "ok", result.reason
    assert result.used_required_const is False


@pytest.mark.lean
def test_probe_missing_target_is_unknown(synthetic_module):
    result = probe_proof_size(
        f"{synthetic_module}.does_not_exist",
        repo=ROOT,
        imports=[synthetic_module],
        timeout=120,
    )
    assert result.verdict == "unknown"
    assert result.term_size is None
    assert "not found" in result.reason.lower() or "probe_error" in result.reason.lower()
