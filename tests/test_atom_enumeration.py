from pathlib import Path

import pytest

from solve.experiments.spec import load_experiment_spec
from solve.lean.atoms import enumerate_atoms

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.lean
def test_enumerate_atoms_run0_seed_limit_5():
    spec = load_experiment_spec(ROOT / "experiments" / "run0_nat_control.yaml").model_copy(
        update={"corpus": load_experiment_spec(ROOT / "experiments" / "run0_nat_control.yaml").corpus.model_copy(update={"seed_limit": 5})}
    )
    records = enumerate_atoms(spec, repo=ROOT, timeout=300)
    assert len(records) >= 1
    assert len(records) <= 5
    assert all(record.name.startswith("Nat.") for record in records)
    assert all(record.type_pp for record in records)
    assert all(record.type_hash for record in records)
    assert any(isinstance(record.axioms, list) or record.axioms is None for record in records)
    assert all(record.axioms != "unknown" for record in records)
