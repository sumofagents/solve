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
from solve.loop import run_control


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
    try:
        metrics = run_control(
            args.spec,
            repo=repo,
            out_receipts=out_receipts,
            out_metrics=out_metrics,
            max_candidates=args.max_candidates,
            timeout=args.timeout,
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
    run_control_parser.set_defaults(func=command_run_control)

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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
