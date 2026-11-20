from tests.plo_rules_reference import run


def test_engine_matches_independent_rules_reference_on_random_hands():
    mismatches, examples = run(3_000, seed=5)
    assert not mismatches, examples
