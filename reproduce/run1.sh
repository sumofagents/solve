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
solve run-control experiments/run1_list_basic_depth2.yaml \
  --out runs/run1/receipts.jsonl \
  --metrics runs/run1/metrics.json \
  --max-candidates 50
solve classify-value experiments/run1_list_basic_depth2.yaml \
  --receipts runs/run1/receipts.jsonl \
  --out runs/run1/value_classified.jsonl \
  --metrics runs/run1/value_metrics.json \
  --max-receipts 50
solve promote experiments/run1_list_basic_depth2.yaml \
  --classified runs/run1/value_classified.jsonl \
  --out runs/run1/promoted.jsonl
python -m pytest
python -m pytest -m lean
