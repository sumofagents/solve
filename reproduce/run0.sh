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
  echo "mathlib cache unavailable; falling back to lake build Mathlib.Data.Nat.Basic"
  lake build Mathlib.Data.Nat.Basic
fi
solve validate experiments/run0_nat_control.yaml
solve check-imports experiments/run0_nat_control.yaml
solve enumerate-atoms experiments/run0_nat_control.yaml --out .hermes/atoms_run0.json
solve run-control experiments/run0_nat_control.yaml \
  --out runs/run0/receipts.jsonl \
  --metrics runs/run0/metrics.json \
  --max-candidates 10
solve classify-triviality experiments/run0_nat_control.yaml \
  --receipts runs/run0/receipts.jsonl \
  --out runs/run0/classified.jsonl \
  --metrics runs/run0/classification_metrics.json
python -m pytest
python -m pytest -m lean
