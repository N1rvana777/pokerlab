import json
from pathlib import Path

import pytest

from pokerlab.solver.reference import cards, rank, river_matrix, equilibrium_value, quads_barrel_reference
from pokerlab.solver.__main__ import save_result


def test_kickers_wheel_ties_and_conflicts():
    assert rank(cards("AsAhKdQcJs")) > rank(cards("AcAdKhQdTs"))
    assert rank(cards("As2h3d4c5s")) < rank(cards("2s3h4d5c6s"))
    board = cards("AsKsQsJsTs")
    assert rank(board+cards("2c3c")) == rank(board+cards("9h9d"))
    with pytest.raises(ValueError):
        cards("AsAs")
    with pytest.raises(ValueError):
        river_matrix("2c3d7h8s9c", [[("AsAh", 1)], [("AsKh", 1)]], 20, 10)


def test_constant_sum_nuts_equilibrium():
    a = river_matrix("AcAd2h3s4c", [[("AsAh", 1)], [("KcKd", 1)]], 20, 10)
    assert equilibrium_value(a) == pytest.approx(20)


def test_no_clairvoyant_response():
    # One hero hand cannot choose a different action against two hidden hands.
    a = river_matrix("2c3d7h8s9c", [[("KsKh", 1)], [("AsAh", 1), ("QcJd", 1)]], 20, 10)
    assert equilibrium_value(a) < 15  # clairvoyant per-deal maxima would exceed this


@pytest.mark.parametrize("street,q,expected", [(3, 0, 45), (3, 1, 50), (4, 0, 35), (4, 1, 40), (5, 0, 25), (5, 1, 30)])
def test_independent_barrel_values(street, q, expected):
    assert quads_barrel_reference(street, q)["ev"] == expected


def test_atomic_result_roundtrip(tmp_path):
    path = tmp_path/"result.json"
    save_result(path, {"schema_version": 1, "ev": [12, 8]})
    assert json.loads(path.read_text()) == {"schema_version": 1, "ev": [12, 8]}
    assert list(tmp_path.iterdir()) == [path]
