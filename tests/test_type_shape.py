from solve.grammar.type_shape import parse_equality, parse_iff, parse_implication


def test_parse_equality_positive_and_binder_cases():
    assert parse_equality("a = b") == ("a", "b")
    parsed = parse_equality("∀ n, n + 0 = n")
    assert parsed == ("n + 0", "n")
    assert parsed.binders == "∀ n,"
    assert parse_equality("(a = b) = c") == ("(a = b)", "c")


def test_parse_equality_rejects_malformed_or_ambiguous_text():
    assert parse_equality("a = b = c") is None
    assert parse_equality("a = (b") is None
    assert parse_equality("a ↔ b") is None


def test_parse_iff_positive_negative_and_binder_cases():
    assert parse_iff("P ↔ Q") == ("P", "Q")
    parsed = parse_iff("∀ n, P n ↔ Q n")
    assert parsed == ("P n", "Q n")
    assert parsed.binders == "∀ n,"
    assert parse_iff("P ↔ Q ↔ R") is None
    assert parse_iff("P → Q") is None


def test_parse_implication_positive_negative_and_binder_cases():
    assert parse_implication("P → Q") == ("P", "Q")
    assert parse_implication("P -> Q") == ("P", "Q")
    parsed = parse_implication("∀ n, P n → Q n")
    assert parsed == ("P n", "Q n")
    assert parsed.binders == "∀ n,"
    assert parse_implication("P → Q → R") is None
    assert parse_implication("(P → Q") is None
