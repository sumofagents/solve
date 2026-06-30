"""Command-line entry point for solve."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from solve.experiments.spec import load_experiment_spec
from solve.lean.atoms import enumerate_atoms
from solve.lean.replay import find_tool, replay_file, write_smoke_module
from solve.lean.triviality import classify_triviality
from solve.lean.value import classify_value
from solve.loop import run_control
from solve.promote import promote


def _run(cmd: list[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)


def command_doctor(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    print(f"repo: {repo}")

    lean = find_tool("lean")
    lake = find_tool("lake")
    for tool, cmd in [("lean", [lean, "--version"]), ("lake", [lake, "--version"] )]:
        result = _run(cmd, repo)
        if result.returncode != 0:
            print(f"{tool}: FAIL", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            return result.returncode
        print(f"{tool}: {result.stdout.strip()}")

    toolchain = repo / "lean-toolchain"
    if not toolchain.exists():
        print("lean-toolchain: missing", file=sys.stderr)
        return 1
    print(f"lean-toolchain: {toolchain.read_text(encoding='utf-8').strip()}")

    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False, encoding="utf-8") as fh:
        fh.write("theorem solve_doctor_smoke : 1 + 1 = 2 := by\n  rfl\n")
        smoke = Path(fh.name)
    try:
        result = replay_file(smoke, cwd=repo)
        if result.returncode != 0:
            print("lean smoke: FAIL", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            return result.returncode
        print("lean smoke: PASS")
    finally:
        smoke.unlink(missing_ok=True)

    if (repo / "lakefile.lean").exists():
        generated = repo / "lean" / "Solve" / "Generated" / "Epoch0.lean"
        if not generated.exists():
            write_smoke_module(generated)
        result = replay_file(generated, cwd=repo)
        if result.returncode != 0:
            print("lake replay smoke: FAIL", file=sys.stderr)
            print(result.stdout, file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            return result.returncode
        print("lake replay smoke: PASS")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    for spec_path in args.specs:
        spec = load_experiment_spec(spec_path)
        print(
            f"VALID {spec_path}: name={spec.name} imports={','.join(spec.lean.imports)} "
            f"operators={len(spec.grammar.all_operators)} max_depth={spec.bounds.max_depth}"
        )
    return 0


def _safe_generated_suffix(name: str) -> str:
    suffix = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name).strip("_")
    if not suffix:
        suffix = "spec"
    if suffix[0].isdigit():
        suffix = f"spec_{suffix}"
    return suffix


def _write_import_probe(spec_path: str, repo: Path) -> Path:
    spec = load_experiment_spec(spec_path)
    target = repo / "lean" / "Solve" / "Generated" / f"ImportProbe_{_safe_generated_suffix(spec.name)}.lean"
    target.parent.mkdir(parents=True, exist_ok=True)
    imports = "\n".join(f"import {imp}" for imp in spec.lean.imports)
    target.write_text(f"{imports}\n\n#check True\n", encoding="utf-8")
    return target


def command_check_imports(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    failed = False
    for spec_path in args.specs:
        target = _write_import_probe(spec_path, repo)
        result = replay_file(target, cwd=repo, timeout=args.timeout)
        if result.returncode == 0:
            target.unlink(missing_ok=True)
            print(f"IMPORTS_OK {spec_path}")
        else:
            failed = True
            print(f"IMPORTS_FAIL {spec_path}", file=sys.stderr)
            if result.stdout:
                print(result.stdout, end="", file=sys.stderr)
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
    return 1 if failed else 0


def command_enumerate_atoms(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    spec = load_experiment_spec(args.spec)
    try:
        records = enumerate_atoms(spec, repo=repo, timeout=args.timeout)
    except Exception as exc:
        print(f"ATOM_ENUM_FAIL {args.spec}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    payload = {
        "spec": args.spec,
        "records": [record.model_dump(mode="json") for record in records],
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = repo / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered + "\n", encoding="utf-8")
        print(f"ATOMS_OK {args.spec} count={len(records)} out={out}")
    else:
        print(rendered)
    return 0


def command_replay_smoke(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    target = Path(args.path) if args.path else repo / "lean" / "Solve" / "Generated" / "Epoch0.lean"
    if not target.is_absolute():
        target = repo / target
    write_smoke_module(target)
    result = replay_file(target, cwd=repo)
    print(f"replay command: lake env lean {target}")
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode == 0:
        print("replay smoke: PASS")
    else:
        print("replay smoke: FAIL", file=sys.stderr)
    return result.returncode


def _resolve_output_path(path: str, repo: Path) -> Path:
    out = Path(path)
    if not out.is_absolute():
        out = repo / out
    return out


def command_run_control(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    out_receipts = _resolve_output_path(args.out, repo)
    out_metrics = _resolve_output_path(args.metrics, repo) if args.metrics else None
    extend_with = _resolve_output_path(args.extend_with, repo) if args.extend_with else None
    try:
        metrics = run_control(
            args.spec,
            repo=repo,
            out_receipts=out_receipts,
            out_metrics=out_metrics,
            max_candidates=args.max_candidates,
            timeout=args.timeout,
            epoch=args.epoch,
            extend_with=extend_with,
        )
    except Exception as exc:
        print(f"RUN_CONTROL_FAIL {args.spec}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"RUN_CONTROL_OK {args.spec} candidates={metrics.candidate_count} "
        f"retained={metrics.retained_count} out={out_receipts}"
    )
    return 0


def command_promote(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    classified = _resolve_output_path(args.classified, repo)
    out_promoted = _resolve_output_path(args.out, repo)
    metrics_path = _resolve_output_path(args.metrics, repo) if args.metrics else None
    try:
        metrics = promote(
            args.spec,
            repo=repo,
            classified_path=classified,
            out_promoted=out_promoted,
            metrics_path=metrics_path,
            timeout=args.timeout,
        )
    except Exception as exc:
        print(f"PROMOTE_FAIL {args.spec}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    module = metrics.promoted_module if metrics.promoted_module is not None else "none"
    print(
        f"PROMOTE_OK {args.spec} promoted={metrics.promoted_count} "
        f"module={module} out={out_promoted}"
    )
    return 0


def command_classify_triviality(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    receipts = _resolve_output_path(args.receipts, repo)
    out_classified = _resolve_output_path(args.out, repo)
    out_metrics = _resolve_output_path(args.metrics, repo) if args.metrics else None
    try:
        metrics = classify_triviality(
            args.spec,
            repo=repo,
            receipts_path=receipts,
            out_path=out_classified,
            metrics_path=out_metrics,
            heartbeat_budget=args.heartbeat_budget,
            step_budget=args.step_budget,
            timeout_seconds=args.timeout,
            max_receipts=args.max_receipts,
        )
    except Exception as exc:
        print(f"CLASSIFY_TRIVIALITY_FAIL {args.spec}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"CLASSIFY_TRIVIALITY_OK {args.spec} classified={metrics.retained_receipts_classified} "
        f"trivial_by_automation={metrics.counts_by_automation_classification.get('trivial_by_automation', 0)} "
        f"out={out_classified}"
    )
    return 0


def command_classify_value(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    receipts = _resolve_output_path(args.receipts, repo)
    out_classified = _resolve_output_path(args.out, repo)
    out_metrics = _resolve_output_path(args.metrics, repo)
    promoted_prefixes: list[str] | None = None
    if getattr(args, "promoted", None):
        promoted_path = _resolve_output_path(args.promoted, repo)
        from solve.verify.promoted import read_promoted_jsonl

        records = read_promoted_jsonl(promoted_path)
        if records:
            promoted_prefixes = sorted({r.promoted_module for r in records})
    try:
        metrics = classify_value(
            args.spec,
            repo=repo,
            receipts_path=receipts,
            out_path=out_classified,
            metrics_path=out_metrics,
            heartbeat_budget=args.heartbeat_budget,
            step_budget=args.step_budget,
            timeout_seconds=args.timeout,
            novelty_candidate_cap=args.novelty_candidate_cap,
            novelty_heartbeat_budget=args.novelty_heartbeat_budget,
            novelty_timeout_seconds=args.novelty_timeout,
            novelty_global_timeout_seconds=args.novelty_global_timeout,
            novelty_scope=args.novelty_scope,
            novelty_verify_mode=args.novelty_verify_mode,
            max_receipts=args.max_receipts,
            promoted_prefixes=promoted_prefixes,
        )
    except Exception as exc:
        print(f"CLASSIFY_VALUE_FAIL {args.spec}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"CLASSIFY_VALUE_OK {args.spec} classified={metrics.retained_receipts_classified} "
        f"promotable={metrics.counts_by_promotable.get('true', 0)} "
        f"novel={metrics.counts_by_novelty_classification.get('novel_in_imported_env', 0)} "
        f"structural={metrics.counts_by_structural_packaging.get('true', 0)} "
        f"ingredient_trivial={metrics.counts_by_ingredient_trivial.get('true', 0)} "
        f"out={out_classified}"
    )
    return 0


def command_mark_downstream_used(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    epoch0_receipts = _resolve_output_path(args.epoch0_receipts, repo)
    epoch1_receipts = _resolve_output_path(args.epoch1_receipts, repo)
    promoted = _resolve_output_path(args.promoted, repo)
    try:
        from solve.lean.downstream import mark_downstream_used

        summary = mark_downstream_used(
            args.spec,
            repo=repo,
            epoch0_receipts_path=epoch0_receipts,
            epoch1_receipts_path=epoch1_receipts,
            promoted_path=promoted,
            timeout=args.timeout,
            heartbeat_budget=args.heartbeat_budget,
            rec_depth=args.rec_depth,
            max_constants=args.max_constants,
            max_receipts=args.max_receipts,
        )
    except Exception as exc:
        print(f"DOWNSTREAM_USED_FAIL {args.spec}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"DOWNSTREAM_USED_OK epoch0={summary.epoch0} promoted={summary.promoted} "
        f"used={summary.used} consumers={summary.consumers} probe_unknown={summary.probe_unknown}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="solve")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check Python/Lean/Lake and replay smoke readiness")
    doctor.add_argument("--repo", default=".")
    doctor.set_defaults(func=command_doctor)

    validate = sub.add_parser("validate", help="validate one or more ExperimentSpec YAML/JSON files")
    validate.add_argument("specs", nargs="+")
    validate.set_defaults(func=command_validate)

    check_imports = sub.add_parser("check-imports", help="validate Lean imports for one or more specs")
    check_imports.add_argument("specs", nargs="+")
    check_imports.add_argument("--repo", default=".")
    check_imports.add_argument("--timeout", type=int, default=300)
    check_imports.set_defaults(func=command_check_imports)

    enumerate_atoms_parser = sub.add_parser("enumerate-atoms", help="enumerate seed atoms from imported Lean environments")
    enumerate_atoms_parser.add_argument("spec")
    enumerate_atoms_parser.add_argument("--out", default=None)
    enumerate_atoms_parser.add_argument("--repo", default=".")
    enumerate_atoms_parser.add_argument("--timeout", type=int, default=300)
    enumerate_atoms_parser.set_defaults(func=command_enumerate_atoms)

    replay_smoke = sub.add_parser("replay-smoke", help="write and replay a generated Lean smoke theorem")
    replay_smoke.add_argument("--repo", default=".")
    replay_smoke.add_argument("--path", default=None)
    replay_smoke.set_defaults(func=command_replay_smoke)

    run_control_parser = sub.add_parser("run-control", help="run the phase-2 And.intro structural control")
    run_control_parser.add_argument("spec")
    run_control_parser.add_argument("--out", required=True)
    run_control_parser.add_argument("--metrics", default=None)
    run_control_parser.add_argument("--max-candidates", type=int, default=10)
    run_control_parser.add_argument("--repo", default=".")
    run_control_parser.add_argument("--timeout", type=int, default=600)
    run_control_parser.add_argument("--epoch", type=int, choices=[0, 1], default=0)
    run_control_parser.add_argument("--extend-with", default=None)
    run_control_parser.set_defaults(func=command_run_control)

    promote_parser = sub.add_parser("promote", help="promote value-classified receipts into replayed atoms")
    promote_parser.add_argument("spec")
    promote_parser.add_argument("--classified", required=True)
    promote_parser.add_argument("--out", required=True)
    promote_parser.add_argument("--metrics", default=None)
    promote_parser.add_argument("--repo", default=".")
    promote_parser.add_argument("--timeout", type=int, default=600)
    promote_parser.set_defaults(func=command_promote)

    classify_parser = sub.add_parser(
        "classify-triviality",
        help="classify retained receipts with bounded Lean automation",
    )
    classify_parser.add_argument("spec")
    classify_parser.add_argument("--receipts", required=True)
    classify_parser.add_argument("--out", required=True)
    classify_parser.add_argument("--metrics", required=True)
    classify_parser.add_argument("--heartbeat-budget", type=int, default=20_000)
    classify_parser.add_argument("--step-budget", type=int, default=1_000)
    classify_parser.add_argument("--timeout", type=int, default=30)
    classify_parser.add_argument("--max-receipts", type=int, default=None)
    classify_parser.add_argument("--repo", default=".")
    classify_parser.set_defaults(func=command_classify_triviality)

    value_parser = sub.add_parser(
        "classify-value",
        help="classify retained receipts by truth, novelty, triviality, and interestingness",
    )
    value_parser.add_argument("spec")
    value_parser.add_argument("--receipts", required=True)
    value_parser.add_argument("--out", required=True)
    value_parser.add_argument("--metrics", required=True)
    value_parser.add_argument("--heartbeat-budget", type=int, default=20_000)
    value_parser.add_argument("--step-budget", type=int, default=1_000)
    value_parser.add_argument("--timeout", type=int, default=30)
    value_parser.add_argument("--novelty-candidate-cap", type=int, default=500_000)
    value_parser.add_argument("--novelty-heartbeat-budget", type=int, default=2_000_000)
    value_parser.add_argument("--novelty-timeout", type=int, default=60)
    value_parser.add_argument("--novelty-global-timeout", type=int, default=900)
    value_parser.add_argument("--novelty-scope", choices=["imported", "global"], default="imported")
    value_parser.add_argument("--novelty-verify-mode", choices=["discrtree", "brute"], default="brute")
    value_parser.add_argument("--max-receipts", type=int, default=None)
    value_parser.add_argument("--promoted", default=None, help="promoted.jsonl path for epoch >= 1 novelty refinement")
    value_parser.add_argument("--repo", default=".")
    value_parser.set_defaults(func=command_classify_value)

    downstream_parser = sub.add_parser(
        "mark-downstream-used",
        help="mark epoch-0 receipts used by retained epoch-1 promoted-atom consumers",
    )
    downstream_parser.add_argument("spec")
    downstream_parser.add_argument("--epoch0-receipts", required=True)
    downstream_parser.add_argument("--epoch1-receipts", required=True)
    downstream_parser.add_argument("--promoted", required=True)
    downstream_parser.add_argument("--repo", default=".")
    downstream_parser.add_argument("--timeout", type=int, default=60)
    downstream_parser.add_argument("--heartbeat-budget", type=int, default=20_000)
    downstream_parser.add_argument("--rec-depth", type=int, default=1_000)
    downstream_parser.add_argument("--max-constants", type=int, default=10_000)
    downstream_parser.add_argument("--max-receipts", type=int, default=None)
    downstream_parser.set_defaults(func=command_mark_downstream_used)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
