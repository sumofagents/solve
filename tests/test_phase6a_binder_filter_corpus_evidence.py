import json
import os

import pytest

from solve.grammar.congr_arg import generate_congr_arg_candidates
from solve.grammar.eq_symm import generate_eq_symm_candidates
from solve.grammar.eq_trans import generate_eq_trans_candidates
from solve.grammar.iff_intro import generate_iff_intro_candidates
from solve.grammar.iff_mp import generate_iff_mp_candidates
from solve.grammar.iff_mpr import generate_iff_mpr_candidates
from solve.lean.atoms import AtomRecord


ATOM_DUMP = ".hermes/atoms_run1.json"


@pytest.mark.skipif(not os.path.exists(ATOM_DUMP), reason=".hermes/atoms_run1.json not present")
def test_phase6a_binder_filter_corpus_evidence():
    with open(ATOM_DUMP, encoding="utf-8") as handle:
        payload = json.load(handle)

    rows = payload["records"] if isinstance(payload, dict) and "records" in payload else payload
    atoms = [AtomRecord.model_validate(row) for row in rows]

    assert len(generate_eq_symm_candidates(atoms, max_candidates=50, experiment_name="run1")) <= 1
    assert len(generate_eq_trans_candidates(atoms, max_candidates=50, experiment_name="run1")) == 0
    assert len(generate_iff_mp_candidates(atoms, max_candidates=50, experiment_name="run1")) == 0
    assert len(generate_iff_mpr_candidates(atoms, max_candidates=50, experiment_name="run1")) == 0
    assert len(generate_iff_intro_candidates(atoms, max_candidates=50, experiment_name="run1")) == 0
    assert len(generate_congr_arg_candidates(atoms, max_candidates=50, experiment_name="run1")) == 0
