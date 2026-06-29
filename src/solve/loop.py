"""Core loop boundary.

This module is intentionally connector-free. Language connectors may prepare
ExperimentSpec values and explain receipts, but they are not imported by the
retention/replay path.
"""

from __future__ import annotations

from solve.experiments.spec import ExperimentSpec


def retention_gate_summary(spec: ExperimentSpec) -> dict[str, object]:
    """Return the mechanical gates a run must satisfy before promotion."""
    return {
        "experiment": spec.name,
        "requires_replay": spec.promotion.require_replay,
        "requires_not_existing_defeq": spec.promotion.require_not_existing_defeq,
        "operators": spec.grammar.all_operators,
    }
