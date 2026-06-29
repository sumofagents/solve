import json
import os

import pytest

from solve.grammar.eq_symm import generate_eq_symm_candidates
from solve.grammar.eq_trans import generate_eq_trans_candidates
from solve.grammar.iff_intro import generate_iff_intro_candidates
from solve.grammar.iff_mp import generate_iff_mp_candidates
from solve.grammar.iff_mpr import generate_iff_mpr_candidates
from solve.lean.atoms import AtomRecord


ATOM_DUMP = ".hermes/atoms_run1.json"


@pytest.mark.skipif(not os.path.exists(ATOM_DUMP), reason=".hermes/atoms_run1.json not present")
def test_phase6a_binder_filter_corpus_evidence():
    """Lock the honest projection for typed operators that depend ONLY on atom
    corpus topology (not replay). congrArg is excluded because its candidate
    count depends on the arity>=1 function pool, not just bare-proposition
    topology — replay is the truth gate for those candidates."""
    with open(ATOM_DUMP, encoding="utf-8") as handle:
        payload = json.load(handle)

    rows = payload["records"] if isinstance(payload, dict) and "records" in payload else payload
    atoms = [AtomRecord.model_validate(row) for row in rows]

    # Only 1 theorem has binder_count==0 in the List.Basic corpus (List.utf8Encode_nil)
    # and it parses as an equality. So Eq.symm produces <=1 candidate.
    assert len(generate_eq_symm_candidates(atoms, max_candidates=50, experiment_name="run1")) <= 1
    # No 2nd bare equality with matching middle term -> 0
    assert len(generate_eq_trans_candidates(atoms, max_candidates=50, experiment_name="run1")) == 0
    # 0 bare-iff atoms -> 0
    assert len(generate_iff_mp_candidates(atoms, max_candidates=50, experiment_name="run1")) == 0
    assert len(generate_iff_mpr_candidates(atoms, max_candidates=50, experiment_name="run1")) == 0
    # 0 bare-implication atoms -> 0
    assert len(generate_iff_intro_candidates(atoms, max_candidates=50, experiment_name="run1")) == 0
