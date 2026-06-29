"""Command-line entry point for solve."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from solve.experiments.spec import load_experiment_spec
from solve.lean.replay import find_tool, replay_file, write_smoke_module


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
        result = _run([lean, str(smoke)], repo)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="solve")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check Python/Lean/Lake and replay smoke readiness")
    doctor.add_argument("--repo", default=".")
    doctor.set_defaults(func=command_doctor)

    validate = sub.add_parser("validate", help="validate one or more ExperimentSpec YAML/JSON files")
    validate.add_argument("specs", nargs="+")
    validate.set_defaults(func=command_validate)

    replay_smoke = sub.add_parser("replay-smoke", help="write and replay a generated Lean smoke theorem")
    replay_smoke.add_argument("--repo", default=".")
    replay_smoke.add_argument("--path", default=None)
    replay_smoke.set_defaults(func=command_replay_smoke)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
