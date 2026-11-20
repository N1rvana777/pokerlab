from pokerlab.plo.agents import CallingStation, RandomAgent, RuleAgent
from pokerlab.plo.engine import TableRules
from pokerlab.plo.session import SessionConfig, run_session

RULES = TableRules(50, 100)


def agents(n, offset=0):
    return [RandomAgent(seed=offset + k) for k in range(n)]


def test_reset_mode_restarts_every_hand_and_rotates_button():
    records = []
    cfg = SessionConfig(RULES, (5_000, 12_000, 800), "reset", hands=12, seed=4)
    result = run_session(cfg, agents(3), records.append)
    assert [r["starting_stacks"] for r in records] == [[5_000, 12_000, 800]] * 12
    assert [r["button_seat"] for r in records] == [h % 3 for h in range(12)]
    assert sum(lg.net for lg in result.ledgers) == 0
    assert all(lg.stack == s for lg, s in zip(result.ledgers, cfg.starting_stacks))


def test_carry_mode_rebuys_are_not_winnings_and_chips_are_conserved():
    cfg = SessionConfig(RULES, (300, 300, 300, 300), "carry", "rebuy", hands=300, seed=2)
    result = run_session(cfg, agents(4))
    assert result.hands_played == 300
    assert sum(lg.rebuys for lg in result.ledgers) > 0
    assert sum(lg.stack for lg in result.ledgers) == 1_200 + sum(lg.rebuy_chips for lg in result.ledgers)
    for lg in result.ledgers:
        assert lg.net == lg.stack - 300 - lg.rebuy_chips


def test_carry_mode_leave_and_stop_policies():
    leave = run_session(SessionConfig(RULES, (300,) * 4, "carry", "leave", hands=2_000, seed=2), agents(4))
    gone = [lg for lg in leave.ledgers if not lg.active]
    assert gone and all(lg.stack == 0 for lg in gone)
    assert sum(lg.stack for lg in leave.ledgers) == 1_200
    stop = run_session(SessionConfig(RULES, (300,) * 4, "carry", "stop", hands=2_000, seed=2), agents(4))
    assert stop.stop_reason.startswith("a player busted") and stop.hands_played < 2_000


def test_carry_mode_uneven_stacks_eight_players_with_mixed_agents():
    stacks = (10_000, 4_000, 25_000, 10_000, 6_000, 15_000, 10_000, 2_000)
    players = [RuleAgent(), RandomAgent(1), CallingStation(), RuleAgent(12.0, 8.0),
               RandomAgent(2), CallingStation(), RuleAgent(), RandomAgent(3)]
    result = run_session(SessionConfig(RULES, stacks, "carry", "rebuy", hands=200, seed=8), players)
    assert result.hands_played == 200
    assert sum(lg.stack for lg in result.ledgers) == sum(stacks) + sum(lg.rebuy_chips for lg in result.ledgers)


def test_sessions_are_reproducible():
    runs = []
    for _ in range(2):
        records = []
        run_session(SessionConfig(RULES, (2_000,) * 5, "carry", "rebuy", hands=40, seed=6),
                    agents(5, offset=10), records.append)
        runs.append(records)
    assert runs[0] == runs[1]
