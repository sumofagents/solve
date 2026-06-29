from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path

import yaml

from solve.experiments.spec import ExperimentSpec, load_experiment_spec
from solve.lean.codegen import write_run_control_module
from solve.verify.candidates import GeneratedCandidate, make_candidate_id
from solve.verify.receipts import CandidateReceipt, ReplayResult


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PARENTS = ("Nat.zero_lt_one", "Nat.zero_lt_one")
DEFAULT_STATEMENT = "0 < 1 ∧ 0 < 1"
DEFAULT_PROOF_TERM = "And.intro (@Nat.zero_lt_one) (@Nat.zero_lt_one)"


def safe_suffix(name: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_")
    if not suffix:
        suffix = "spec"
    if suffix[0].isdigit():
        suffix = f"spec_{suffix}"
    return suffix


def write_phase5a_spec(
    tmp_path: Path,
    name: str,
    *,
    seed_limit: int = 5,
    namespace_prefixes: list[str] | None = None,
) -> tuple[Path, ExperimentSpec]:
    base = load_experiment_spec(ROOT / "experiments" / "run0_nat_control.yaml")
    spec = base.model_copy(
        update={
            "name": name,
            "corpus": base.corpus.model_copy(
                update={
                    "seed_limit": seed_limit,
                    **({"namespace_prefixes": namespace_prefixes} if namespace_prefixes is not None else {}),
                }
            ),
        }
    )
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    return path, spec


def cleanup_generated_for(*spec_names: str) -> None:
    generated = ROOT / "lean" / "Solve" / "Generated"
    for name in spec_names:
        suffix = safe_suffix(name)
        for path in [
            generated / f"RunControl_{suffix}.lean",
            generated / f"RunControl_{safe_suffix(f'{name}_epoch1')}.lean",
            generated / f"Promoted_{suffix}.lean",
        ]:
            path.unlink(missing_ok=True)
        for path in generated.glob(f"RunControl_{suffix}_*.lean"):
            path.unlink(missing_ok=True)


def source_module_name(spec: ExperimentSpec) -> str:
    return f"Solve.Generated.RunControl_{safe_suffix(spec.name)}"


def promoted_module_name(spec: ExperimentSpec) -> str:
    return f"Solve.Generated.Promoted_{safe_suffix(spec.name)}"


def write_source_run_control_module(spec: ExperimentSpec) -> Path:
    candidate = GeneratedCandidate(
        candidate_id=make_candidate_id("And.intro", DEFAULT_PARENTS, 1),
        operator="And.intro",
        parents=DEFAULT_PARENTS,
        depth=1,
        generated_theorem_name="Solve.Generated.RunControl.solve_generated_0",
        parent_atom_kinds=("theorem", "theorem"),
    )
    return write_run_control_module([candidate], repo=ROOT, spec=spec, module_suffix=spec.name)


def promoted_classified_row(
    spec: ExperimentSpec,
    *,
    record_id: str = "cand_phase5a_promote",
    generated_theorem_name: str = "Solve.Generated.RunControl.solve_generated_0",
    proof_term: str = DEFAULT_PROOF_TERM,
    statement: str = DEFAULT_STATEMENT,
    promotable: bool = True,
    epoch: int = 0,
) -> dict[str, object]:
    normalized_hash = "sha256:" + hashlib.sha256(statement.encode("utf-8")).hexdigest()
    receipt = CandidateReceipt(
        record_id=record_id,
        experiment_id=spec.name,
        toolchain=spec.lean.toolchain,
        imports=list(spec.lean.imports),
        statement=statement,
        proof_term=proof_term,
        generated_theorem_name=generated_theorem_name,
        parents=list(DEFAULT_PARENTS),
        operator="And.intro",
        depth=1,
        normalized_statement_hash=normalized_hash,
        axioms_used=[],
        replay=ReplayResult(
            command=["lake", "env", "lean", f"lean/Solve/Generated/RunControl_{safe_suffix(spec.name)}.lean"],
            exit_code=0,
        ),
        structural_packaging=False,
        ingredient_trivial_by_automation=False,
        from_scratch_closure="not_closed",
        novelty_classification="novel_in_imported_env",
        promotable=promotable,
        interestingness_classification="unknown",
        epoch=epoch,
    )
    row = receipt.model_dump(mode="json")
    row["structural_packaging_reason"] = "synthetic non-structural fixture"
    row["ingredient_trivial_closed_by"] = None
    return row


def write_jsonl_dicts(path: Path, rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return path
