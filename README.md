# solve

Verifier-mediated bounded generation over real verified corpora.

The self-extending grammar experiment: point the architecture proven in [`manifold-destiny`](https://github.com/sumofagents/manifold-destiny) at a large verifiable corpus (mathlib) and produce verified theorems a human had not written.

## Status

Experimental. Architecture plan drafted in [`ARCHITECTURE.md`](ARCHITECTURE.md).

Current scaffold implements the first reproducible gates:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
solve doctor
solve validate experiments/run0_nat_control.yaml experiments/run1_list_basic_depth2.yaml
solve replay-smoke
solve check-imports experiments/run0_nat_control.yaml experiments/run1_list_basic_depth2.yaml
solve enumerate-atoms experiments/run0_nat_control.yaml --out .hermes/atoms_run0.json
solve enumerate-atoms experiments/run1_list_basic_depth2.yaml --out .hermes/atoms_run1.json
python -m pytest
python -m pytest -m lean
bash reproduce/run0.sh
bash reproduce/run1.sh
```

`solve check-imports` renders the spec's bounded imports and runs them under `lake env lean`.
`solve enumerate-atoms` inspects the imported Lean environment and emits machine-readable seed atom records. It does not parse mathlib source text.

The trust boundary is strict:

```text
Language may propose / rank / explain / configure.
Language may not verify or retain truth.
Lean replay receipts are the retention gate.
```

## First experiment sequence

- Run 0: Nat control. Prove the pipeline and quantify how much bounded automation subsumes.
- Run 1: List.Basic discovery attempt. Try to retain a replay-verified, non-defeq, nontrivial theorem that is used downstream.

## What counts

A candidate is retained only after Lean replay succeeds. LLM labels and explanations are advisory metadata, never truth.
