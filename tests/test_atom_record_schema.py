import pytest
from pydantic import ValidationError

from solve.lean.atoms import AtomRecord, parse_atom_line


VALID_PAYLOAD = {
    "name": "Nat.add",
    "kind": "def",
    "type_pp": "Nat -> Nat -> Nat",
    "type_hash": "123",
    "binder_count": 2,
    "arity": 2,
    "module": "Init.Prelude",
    "axioms": [],
}


def test_atom_record_accepts_optional_fields():
    payload = {**VALID_PAYLOAD, "binder_count": None, "arity": None, "module": None, "axioms": None}
    record = AtomRecord.model_validate(payload)
    assert record.binder_count is None
    assert record.axioms is None


def test_atom_record_rejects_missing_required_field():
    payload = dict(VALID_PAYLOAD)
    payload.pop("type_hash")
    with pytest.raises(ValidationError):
        AtomRecord.model_validate(payload)


def test_parse_atom_line_rejects_unknown_axiom_marker():
    line = (
        'ATOM {"name":"Nat.add","kind":"def","type_pp":"Nat","type_hash":"123",'
        '"binder_count":0,"arity":0,"module":null,"axioms":"unknown"}'
    )
    with pytest.raises(ValueError):
        parse_atom_line(line)


def test_parse_atom_line_requires_atom_prefix_and_axioms_field():
    with pytest.raises(ValueError):
        parse_atom_line("{}")
    line = 'ATOM {"name":"Nat.add","kind":"def","type_pp":"Nat","type_hash":"123","binder_count":0,"arity":0,"module":null}'
    with pytest.raises(ValueError):
        parse_atom_line(line)
