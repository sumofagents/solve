#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
solve doctor
solve validate experiments/run0_nat_control.yaml
python -m pytest
python -m pytest -m lean
