from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from solve.experiments.spec import ExperimentSpec, load_experiment_spec

ROOT = Path(__file__).resolve().parents[1]


def test_run_specs_validate():
    for name in ["run0_nat_control.yaml", "run1_list_basic_depth2.yaml"]:
        spec = load_experiment_spec(ROOT / "experiments" / name)
        assert spec.version == 1
        assert spec.promotion.require_replay is True
        assert spec.lean.imports
        assert spec.bounds.promotion_depth >= spec.bounds.max_depth


def test_unknown_operator_rejected():
    data = yaml.safe_load((ROOT / "experiments" / "run0_nat_control.yaml").read_text())
    data["grammar"]["operators"] = ["Eq.symm", "unknown.magic"]
    with pytest.raises(ValidationError, match="unknown operators"):
        ExperimentSpec.model_validate(data)


def test_unbounded_mathlib_import_rejected():
    data = yaml.safe_load((ROOT / "experiments" / "run0_nat_control.yaml").read_text())
    data["lean"]["imports"] = ["Mathlib"]
    with pytest.raises(ValidationError, match="unbounded import Mathlib"):
        ExperimentSpec.model_validate(data)


def test_replay_retention_gate_cannot_be_disabled():
    data = yaml.safe_load((ROOT / "experiments" / "run0_nat_control.yaml").read_text())
    data["promotion"]["require_replay"] = False
    with pytest.raises(ValidationError, match="Lean replay is the retention gate"):
        ExperimentSpec.model_validate(data)
