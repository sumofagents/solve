from solve.grammar.operators import OPERATORS, baseline_operator_names, discovery_operator_names, require_known_operator


def test_operator_names_unique_and_lookup_roundtrips():
    assert len(OPERATORS) == len(set(OPERATORS))
    for name in OPERATORS:
        assert require_known_operator(name).name == name


def test_structural_controls_are_baseline_only():
    baseline = set(baseline_operator_names())
    assert {"And.intro", "Or.inl", "Or.inr"} <= baseline
    assert not baseline & set(discovery_operator_names())
