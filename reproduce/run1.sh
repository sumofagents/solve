#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
solve doctor
if lake exe cache get; then
  echo "mathlib cache: lake exe cache get"
else
  echo "mathlib cache unavailable; falling back to lake build Mathlib.Data.List.Basic"
  lake build Mathlib.Data.List.Basic
fi
solve validate experiments/run1_list_basic_depth2.yaml
solve check-imports experiments/run1_list_basic_depth2.yaml
solve enumerate-atoms experiments/run1_list_basic_depth2.yaml --out .hermes/atoms_run1.json
python -m pytest
python -m pytest -m lean
