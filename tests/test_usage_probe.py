from __future__ import annotations

import pytest

from solve.lean.usage import parse_usage_output


def test_usage_parser_reads_well_formed_output():
    result = parse_usage_output(
        'USAGE {"target":"Solve.Generated.RunControl.consumer","used_promoted":'
        '["Solve.Generated.Promoted.atom_a"],"unknown":false,"reason":""}\n'
        "USAGE_DONE\n"
    )

    assert result.target == "Solve.Generated.RunControl.consumer"
    assert result.used_promoted == ("Solve.Generated.Promoted.atom_a",)
    assert result.unknown is False
    assert result.reason == ""


def test_usage_parser_rejects_missing_done():
    with pytest.raises(RuntimeError, match="USAGE_DONE"):
        parse_usage_output(
            'USAGE {"target":"t","used_promoted":[],"unknown":false,"reason":""}\n'
        )


def test_usage_parser_rejects_malformed_json():
    with pytest.raises(ValueError):
        parse_usage_output("USAGE {bad json}\nUSAGE_DONE\n")


def test_usage_parser_reads_unknown_result():
    result = parse_usage_output(
        'USAGE {"target":"Solve.Generated.RunControl.consumer","used_promoted":[],'
        '"unknown":true,"reason":"constant cap hit"}\n'
        "USAGE_DONE\n"
    )

    assert result.unknown is True
    assert result.reason == "constant cap hit"
