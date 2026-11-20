import numpy as np
import pytest

from pokerlab.plo import evaluate
from pokerlab.plo.agents import CallingStation
from pokerlab.plo.engine import TableRules


class Spy(CallingStation):
    """Remembers every deal it was told about and fails if it is dealt one again."""
    instances: list = []

    def __init__(self) -> None:
        self.seen: set[int] = set()
        Spy.instances.append(self)

    def act(self, obs):
        assert obs.hand_id not in self.seen, "agent saw this deal's summary before playing it"
        return super().act(obs)

    def end_hand(self, summary, seat, players) -> None:
        self.seen.add(summary.hand_id)


def test_duplicate_rotations_are_separate_matches_with_fresh_agents(monkeypatch):
    Spy.instances.clear()
    monkeypatch.setattr(evaluate, "make_agent", lambda spec: Spy())
    blocks = evaluate.run_duplicate(TableRules(50, 100), (10_000,) * 3, [{}, {}, {}], deals=5, seed=1)
    assert len(Spy.instances) == 9        # 3 rotations x 3 agents
    assert blocks.shape == (5, 3) and blocks.sum() == 0


def test_duplicate_puts_every_agent_in_every_seat_once_per_deal():
    records = []
    evaluate.run_duplicate(TableRules(50, 100), (10_000,) * 4, [{"type": "calling_station"}] * 4,
                           deals=6, seed=2, on_hand=records.append)
    for d in range(6):
        seatings = [r["players"] for r in records if r["hand_id"] == d]
        assert len(seatings) == 4
        for agent in range(4):
            assert sorted(s.index(agent) for s in seatings) == [0, 1, 2, 3]
    assert len({tuple(r["players"]) for r in records if r["rotation"] == 0}) > 1


def test_block_summary_units():
    summary = evaluate.block_summary(np.array([100.0, -50.0, 250.0]), hands_per_block=2, big_blind=100)
    assert summary["hands"] == 6 and summary["bb_per_100"] == pytest.approx(50.0)
    assert summary["mbb_per_hand"] == pytest.approx(500.0)
    assert summary["se_bb_per_100"] == pytest.approx(np.std([100, -50, 250], ddof=1) / np.sqrt(3) / 2)
