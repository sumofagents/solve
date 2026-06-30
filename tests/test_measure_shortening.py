"""Tests for the proof-shortening orchestrator (`solve.measure_shortening`)."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from solve.cli import build_parser
from solve.lean.proof_size import ProofSizeResult
from solve.measure_shortening import (
    BenchmarkRow,
    ShorteningRow,
    load_benchmarks,
    measure_shortening,
    summarize,
    write_metrics,
    write_rows,
)


ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_MODULE_NAME = "Solve.Generated.ProofShorteningSynthetic"
SYNTHETIC_PATH = ROOT / "lean" / "Solve" / "Generated" / "ProofShorteningSynthetic.lean"


SYNTHETIC_SRC = """\
namespace Solve.Generated.ProofShorteningSynthetic

theorem promoted_pair : True ∧ True := And.intro True.intro True.intro

theorem without_pair : True ∧ True :=
  let p : True ∧ True := And.intro True.intro True.intro
  let q : True ∧ True := And.intro p.left p.right
  And.intro q.left q.right

theorem with_pair : True ∧ True := promoted_pair

end Solve.Generated.ProofShorteningSynthetic
"""


@pytest.fixture(scope="module")
def synthetic_module():
    SYNTHETIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SYNTHETIC_PATH.write_text(SYNTHETIC_SRC, encoding="utf-8")
    try:
        yield SYNTHETIC_MODULE_NAME
    finally:
        SYNTHETIC_PATH.unlink(missing_ok=True)


# ----------------------------------------------------------- pure verdict logic

def _make_probe_map(
    sizes: Dict[str, Tuple[str, int, bool]],
):
    """Return a fake probe_fn keyed on target name.

    Each entry maps target -> (verdict, term_size, used_required_const_for_with).
    For baseline targets the `used_required_const` field is ignored (None).
    """

    def probe(
        target_name,
        *,
        repo,
        imports,
        required_const=None,
        timeout=60,
        heartbeat_budget=20_000,
        rec_depth=1_000,
    ):
        verdict, term_size, used = sizes[target_name]
        return ProofSizeResult(
            target=target_name,
            verdict=verdict,
            term_size=term_size if verdict == "ok" else None,
            required_const=required_const,
            used_required_const=(used if required_const is not None and verdict == "ok" else None),
            reason="" if verdict == "ok" else "synthetic unknown",
        )

    return probe


def test_verdict_shorter_when_with_smaller_and_usage_confirmed(tmp_path):
    bench = BenchmarkRow(
        benchmark_id="b1",
        imports=("Foo",),
        without_target="Foo.without",
        with_target="Foo.with",
        promoted_const="Foo.helper",
    )
    probe = _make_probe_map({
        "Foo.without": ("ok", 30, False),
        "Foo.with": ("ok", 10, True),
    })
    rows = measure_shortening([bench], repo=tmp_path, probe_fn=probe)
    assert len(rows) == 1
    r = rows[0]
    assert r.verdict == "shorter"
    assert r.delta_absolute == 20
    assert r.delta_ratio == pytest.approx(20 / 30)
    assert r.used_promoted_in_with is True


def test_verdict_not_shorter_when_with_larger(tmp_path):
    bench = BenchmarkRow(
        benchmark_id="b2",
        imports=("Foo",),
        without_target="Foo.without",
        with_target="Foo.with",
        promoted_const="Foo.helper",
    )
    probe = _make_probe_map({
        "Foo.without": ("ok", 10, False),
        "Foo.with": ("ok", 30, True),
    })
    rows = measure_shortening([bench], repo=tmp_path, probe_fn=probe)
    assert rows[0].verdict == "not_shorter"
    assert rows[0].delta_absolute == -20
    assert rows[0].used_promoted_in_with is True


def test_verdict_not_shorter_when_equal(tmp_path):
    bench = BenchmarkRow(
        benchmark_id="b3",
        imports=(),
        without_target="Foo.a",
        with_target="Foo.b",
        promoted_const=None,
    )
    probe = _make_probe_map({
        "Foo.a": ("ok", 5, False),
        "Foo.b": ("ok", 5, False),
    })
    rows = measure_shortening([bench], repo=tmp_path, probe_fn=probe)
    assert rows[0].verdict == "not_shorter"
    assert rows[0].delta_absolute == 0
    assert rows[0].used_promoted_in_with is None


def test_verdict_unknown_when_required_const_not_used(tmp_path):
    bench = BenchmarkRow(
        benchmark_id="b4",
        imports=(),
        without_target="Foo.without",
        with_target="Foo.with",
        promoted_const="Foo.helper",
    )
    probe = _make_probe_map({
        "Foo.without": ("ok", 30, False),
        "Foo.with": ("ok", 5, False),  # smaller but did NOT use helper
    })
    rows = measure_shortening([bench], repo=tmp_path, probe_fn=probe)
    assert rows[0].verdict == "unknown"
    assert "does not use promoted_const" in rows[0].reason
    assert rows[0].used_promoted_in_with is False
    # The arithmetic delta is still reported.
    assert rows[0].delta_absolute == 25


def test_verdict_unknown_when_without_probe_unknown(tmp_path):
    bench = BenchmarkRow(
        benchmark_id="b5",
        imports=(),
        without_target="Foo.without",
        with_target="Foo.with",
        promoted_const=None,
    )
    probe = _make_probe_map({
        "Foo.without": ("unknown", 0, False),
        "Foo.with": ("ok", 5, False),
    })
    rows = measure_shortening([bench], repo=tmp_path, probe_fn=probe)
    assert rows[0].verdict == "unknown"
    assert rows[0].without_size is None
    assert rows[0].with_size == 5
    assert rows[0].delta_absolute is None
    assert rows[0].delta_ratio is None


def test_verdict_unknown_when_with_probe_unknown(tmp_path):
    bench = BenchmarkRow(
        benchmark_id="b6",
        imports=(),
        without_target="Foo.without",
        with_target="Foo.with",
        promoted_const=None,
    )
    probe = _make_probe_map({
        "Foo.without": ("ok", 5, False),
        "Foo.with": ("unknown", 0, False),
    })
    rows = measure_shortening([bench], repo=tmp_path, probe_fn=probe)
    assert rows[0].verdict == "unknown"


def test_summarize_counts(tmp_path):
    rows = [
        ShorteningRow(
            benchmark_id="a",
            without_target="X.a",
            with_target="X.b",
            promoted_const=None,
            without_size=10,
            with_size=5,
            delta_absolute=5,
            delta_ratio=0.5,
            used_promoted_in_with=None,
            verdict="shorter",
            reason="",
        ),
        ShorteningRow(
            benchmark_id="b",
            without_target="X.c",
            with_target="X.d",
            promoted_const=None,
            without_size=5,
            with_size=5,
            delta_absolute=0,
            delta_ratio=0.0,
            used_promoted_in_with=None,
            verdict="not_shorter",
            reason="",
        ),
        ShorteningRow(
            benchmark_id="c",
            without_target="X.e",
            with_target="X.f",
            promoted_const=None,
            without_size=None,
            with_size=None,
            delta_absolute=None,
            delta_ratio=None,
            used_promoted_in_with=None,
            verdict="unknown",
            reason="",
        ),
    ]
    metrics = summarize(rows)
    assert metrics.total == 3
    assert metrics.shortened_count == 1
    assert metrics.unknown_count == 1
    assert metrics.counts_by_verdict == {"shorter": 1, "not_shorter": 1, "unknown": 1}


def test_load_and_write_roundtrip(tmp_path):
    benchmarks_path = tmp_path / "benches.jsonl"
    rows_in = [
        {
            "benchmark_id": "b1",
            "imports": ["Foo"],
            "without_target": "Foo.without",
            "with_target": "Foo.with",
            "promoted_const": "Foo.helper",
        },
        {
            "benchmark_id": "b2",
            "imports": [],
            "without_target": "Foo.a",
            "with_target": "Foo.b",
        },
    ]
    benchmarks_path.write_text(
        "\n".join(json.dumps(r) for r in rows_in) + "\n", encoding="utf-8"
    )
    loaded = load_benchmarks(benchmarks_path)
    assert len(loaded) == 2
    assert loaded[0].benchmark_id == "b1"
    assert loaded[0].promoted_const == "Foo.helper"
    assert loaded[0].imports == ("Foo",)
    assert loaded[1].promoted_const is None

    out_rows = [
        ShorteningRow(
            benchmark_id="b1",
            without_target="Foo.without",
            with_target="Foo.with",
            promoted_const="Foo.helper",
            without_size=10,
            with_size=5,
            delta_absolute=5,
            delta_ratio=0.5,
            used_promoted_in_with=True,
            verdict="shorter",
            reason="ok",
        ),
    ]
    out_path = write_rows(tmp_path / "out.jsonl", out_rows)
    parsed = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert parsed[0]["benchmark_id"] == "b1"
    assert parsed[0]["verdict"] == "shorter"

    metrics_path = write_metrics(tmp_path / "metrics.json", summarize(out_rows))
    metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics_payload["total"] == 1
    assert metrics_payload["shortened_count"] == 1


# ----------------------------------------------------------- real Lean integration

@pytest.mark.lean
def test_real_synthetic_benchmark_returns_shorter(synthetic_module):
    bench = BenchmarkRow(
        benchmark_id="synthetic-pair",
        imports=(synthetic_module,),
        without_target=f"{synthetic_module}.without_pair",
        with_target=f"{synthetic_module}.with_pair",
        promoted_const=f"{synthetic_module}.promoted_pair",
    )
    rows = measure_shortening([bench], repo=ROOT, timeout=180)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "shorter", (row.verdict, row.reason, row.without_size, row.with_size)
    assert row.without_size is not None and row.with_size is not None
    assert row.with_size < row.without_size
    assert row.delta_absolute is not None and row.delta_absolute > 0
    assert row.delta_ratio is not None and row.delta_ratio > 0
    assert row.used_promoted_in_with is True


@pytest.mark.lean
def test_real_synthetic_benchmark_unknown_when_usage_required_but_absent(
    synthetic_module, tmp_path
):
    # Swap with-target to the baseline: usage required but baseline does NOT
    # use promoted_pair => orchestrator must return verdict=unknown.
    bench = BenchmarkRow(
        benchmark_id="synthetic-pair-noflag",
        imports=(synthetic_module,),
        without_target=f"{synthetic_module}.without_pair",
        with_target=f"{synthetic_module}.without_pair",
        promoted_const=f"{synthetic_module}.promoted_pair",
    )
    rows = measure_shortening([bench], repo=ROOT, timeout=180)
    assert rows[0].verdict == "unknown", (rows[0].reason, rows[0].used_promoted_in_with)
    assert rows[0].used_promoted_in_with is False


# ----------------------------------------------------------- CLI smoke

def test_cli_measure_shortening_uses_fake_probe(tmp_path, monkeypatch):
    benchmarks_path = tmp_path / "benches.jsonl"
    benchmarks_path.write_text(
        json.dumps(
            {
                "benchmark_id": "fake1",
                "imports": [],
                "without_target": "Foo.without",
                "with_target": "Foo.with",
                "promoted_const": "Foo.helper",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out_path = tmp_path / "out.jsonl"
    metrics_path = tmp_path / "metrics.json"

    def fake_probe(
        target_name,
        *,
        repo,
        imports,
        required_const=None,
        timeout=60,
        heartbeat_budget=20_000,
        rec_depth=1_000,
    ):
        if target_name == "Foo.without":
            return ProofSizeResult(
                target=target_name,
                verdict="ok",
                term_size=42,
                required_const=required_const,
                used_required_const=None,
                reason="",
            )
        return ProofSizeResult(
            target=target_name,
            verdict="ok",
            term_size=7,
            required_const=required_const,
            used_required_const=True,
            reason="",
        )

    monkeypatch.setattr(
        "solve.measure_shortening.probe_proof_size", fake_probe
    )

    parser = build_parser()
    args = parser.parse_args(
        [
            "measure-shortening",
            "experiments/run0_nat_control.yaml",
            "--benchmarks",
            str(benchmarks_path),
            "--out",
            str(out_path),
            "--metrics",
            str(metrics_path),
            "--repo",
            str(tmp_path),
        ]
    )
    assert int(args.func(args)) == 0
    out_lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(out_lines) == 1
    payload = json.loads(out_lines[0])
    assert payload["verdict"] == "shorter"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics["total"] == 1
    assert metrics["shortened_count"] == 1
