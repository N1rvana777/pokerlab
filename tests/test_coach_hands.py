"""Hand records: PokerStars parsing, replay legality and evidence extraction (synthetic hands only)."""
import copy
from pathlib import Path

import pytest

from pokerlab.coach.evidence import observations, showdowns
from pokerlab.coach.hands import normalize, replay
from pokerlab.coach.pokerstars import parse_text

DATA = Path(__file__).parent / "data" / "coach"


def parsed():
    return {hand["hand_id"]: (hand, r, problems) for hand, r, problems in parse_text((DATA / "pokerstars_synthetic.txt").read_text(encoding="utf-8"))}


def obs_set(hand, r):
    """How observations are derived; a live hand would leave out the rates that need every hand."""
    return {(o.player, o.stat, o.success) for o in observations({**hand, "source": {"kind": "manual"}}, r)}


def live_hand():
    return {"hand_id": "live-20261029-straddle", "source": {"kind": "live_text"},
            "game": {"small_blind": 1, "big_blind": 3, "unit_scale": 1, "currency": "USD"}, "button_seat": 6,
            "players": [{"seat": 1, "name": "Mike", "stack": 300}, {"seat": 2, "name": "Tom", "stack": 500},
                        {"seat": 3, "name": "Hero", "stack": 400, "cards": ["Kc", "Tc"]}, {"seat": 4, "name": "Lee", "stack": 250},
                        {"seat": 5, "name": "Sam", "stack": 300}, {"seat": 6, "name": "Kay", "stack": 350}],
            "posts": [{"player": "Mike", "kind": "sb", "amount": 1}, {"player": "Tom", "kind": "bb", "amount": 3},
                      {"player": "Hero", "kind": "straddle", "amount": 6}],
            "actions": [{"street": "preflop", "player": "Lee", "kind": "raise", "to": 20},
                        {"street": "preflop", "player": "Kay", "kind": "call", "to": 20},
                        {"street": "preflop", "player": "Hero", "kind": "call", "to": 20},
                        {"street": "flop", "player": "Hero", "kind": "check"},
                        {"street": "flop", "player": "Lee", "kind": "bet", "to": 30},
                        {"street": "flop", "player": "Kay", "kind": "call"},
                        {"street": "flop", "player": "Hero", "kind": "fold"},
                        {"street": "turn", "player": "Lee", "kind": "check"},
                        {"street": "turn", "player": "Kay", "kind": "bet", "to": 60},
                        {"street": "turn", "player": "Lee", "kind": "call", "to": 60},
                        {"street": "river", "player": "Lee", "kind": "check"},
                        {"street": "river", "player": "Kay", "kind": "check"}],
            "board": ["Ah", "7c", "2d", "9s", "Kd"],
            "showdown": [{"player": "Lee", "cards": ["Qs", "Jd"]}, {"player": "Kay", "cards": ["7h", "7d"]}],
            "collected": [{"player": "Kay", "amount": 238}], "rake": 6, "hero": "Hero"}


def test_pokerstars_synthetic_hands_parse_and_balance():
    hands = parsed()
    assert sorted(hands) == [f"ps-25000000000{i}" for i in range(1, 5)]
    assert all(problems == [] for _, _, problems in hands.values())
    hand, r, _ = hands["ps-250000000001"]
    assert hand["game"]["unit_scale"] == 100 and hand["game"]["big_blind"] == 100 and hand["hero"] == "Hero"
    assert r.positions == {"Bob": "SB", "Carl": "BB", "Dana": "UTG", "Mike": "HJ", "Anna": "CO", "Hero": "BTN"}
    assert r.pot == 2150 and r.returned == ("Hero", 1200) and hand["rake"] == 100 and r.complete and not r.showdown
    hand, r, _ = hands["ps-250000000002"]
    assert r.showdown and r.pot == 5350 and hand["showdown"] == [{"player": "Mike", "cards": ["Jc", "Td"]}]
    hand, r, _ = hands["ps-250000000003"]
    assert r.returned == ("Mike", 50) and r.pot == 100 and any("死按钮" in w for w in r.warnings)
    hand, r, _ = hands["ps-250000000004"]
    assert r.showdown and r.pot == 6100 and r.saw["flop"] == ["Hero", "Mike"]


def test_evidence_definitions_on_synthetic_hands():
    hands = parsed()
    first = obs_set(*hands["ps-250000000001"][:2])
    assert {("Mike", "open_raise", True), ("Hero", "three_bet", True), ("Mike", "fold_to_three_bet", False),
            ("Hero", "cbet_flop", True), ("Mike", "fold_to_cbet_flop", True), ("Mike", "donk_flop", False),
            ("Mike", "check_raise", False), ("Anna", "three_bet", False)} <= first
    assert not any(p in ("Bob", "Carl") and s == "three_bet" for p, s, _ in first)  # they faced a 3-bet, not one raise
    second = obs_set(*hands["ps-250000000002"][:2])
    assert {("Mike", "open_limp", True), ("Mike", "three_bet", False), ("Mike", "river_bet", True),
            ("Hero", "fold_to_river_bet", False), ("Hero", "cbet_turn", False), ("Mike", "wsd", True),
            ("Hero", "wsd", False), ("Mike", "wtsd", True)} <= second
    walk = obs_set(*hands["ps-250000000003"][:2])
    assert not any(p == "Mike" for p, _, _ in walk)  # big blind walk: no decision, no VPIP opportunity
    allin = obs_set(*hands["ps-250000000004"][:2])
    assert {("Mike", "wtsd", True), ("Hero", "wtsd", True)} <= allin
    hand, r, _ = hands["ps-250000000002"]
    assert showdowns(hand, r)[0]["line"].startswith("翻前 call 1")


def test_live_hand_infers_skipped_folds_and_straddle_order():
    hand = normalize(live_hand())
    r = replay(hand)
    assert r.errors == [] and r.complete and r.showdown
    inferred = [(d.player, d.kind) for d in r.decisions if d.inferred]
    assert inferred == [("Sam", "fold"), ("Mike", "fold"), ("Tom", "fold")]
    assert sum("补记" in w for w in r.warnings) == 3
    assert r.pot == 1 + 3 + 20 + 110 + 110 and r.positions["Hero"] == "UTG"
    seen = obs_set(hand, r)
    assert {("Lee", "open_raise", True), ("Lee", "cbet_flop", True), ("Hero", "fold_to_cbet_flop", True),
            ("Hero", "donk_flop", False), ("Lee", "cbet_turn", False), ("Lee", "fold_to_turn_bet", False),
            ("Kay", "wsd", True), ("Lee", "wsd", False), ("Hero", "wtsd", False)} <= seen
    assert all(o.inferred for o in observations(hand, r) if o.player == "Sam")


def test_blinds_that_disagree_with_the_button_are_flagged():
    assert not any("盲注与按钮" in w for hand, r, _ in parsed().values() for w in r.warnings)
    assert not any("盲注与按钮" in w for w in replay(normalize(live_hand())).warnings)
    moved = live_hand()
    moved["button_seat"] = 4  # by seat order Sam and Kay would post the blinds, but Mike and Tom did
    r = replay(normalize(moved))  # postflop order follows the button, so the recorded turn order also fails
    assert any("盲注与按钮位置不一致" in w and "SB 应是 Sam" in w for w in r.warnings)


def test_straddle_min_raise_is_twice_the_straddle():
    hand = live_hand()
    hand["actions"][0]["to"] = 10  # step 4 < straddle 6
    r = replay(normalize(hand))
    assert any("最小加注" in w for w in r.warnings) and r.errors == []
    hand["source"]["kind"] = "pokerstars"
    r = replay(normalize(hand))
    assert any("行动顺序不符" in e for e in r.errors)  # strict: skipped players are not inferred


def heads_up(actions, **extra):
    hand = {"hand_id": "manual-hu", "source": {"kind": extra.pop("kind", "manual")},
            "game": {"small_blind": 1, "big_blind": 2}, "button_seat": 1,
            "players": [{"seat": 1, "name": "A", "stack": 100}, {"seat": 2, "name": "B", "stack": 100}],
            "posts": [{"player": "A", "kind": "sb", "amount": 1}, {"player": "B", "kind": "bb", "amount": 2}],
            "actions": actions, "board": ["2c", "7d", "9h", "Js", "Kd"]}
    hand.update(extra)
    return replay(normalize(hand))


def test_heads_up_button_acts_first_preflop_and_last_postflop():
    r = heads_up([{"street": "preflop", "player": "A", "kind": "call"}, {"street": "preflop", "player": "B", "kind": "check"},
                  {"street": "flop", "player": "B", "kind": "check"}, {"street": "flop", "player": "A", "kind": "bet", "to": 2},
                  {"street": "flop", "player": "B", "kind": "fold"}])
    assert r.errors == [] and r.positions == {"B": "BB", "A": "BTN"} and r.returned == ("A", 2) and r.pot == 4
    bad = heads_up([{"street": "preflop", "player": "B", "kind": "check"}], kind="pokerstars")
    assert any("行动顺序不符" in e for e in bad.errors)


def test_illegal_actions_are_errors():
    r = heads_up([{"street": "preflop", "player": "A", "kind": "check"}])
    assert any("不能过牌" in e for e in r.errors)
    r = heads_up([{"street": "preflop", "player": "A", "kind": "fold"}, {"street": "preflop", "player": "B", "kind": "check"}])
    assert any("已经结束" in e for e in r.errors)
    r = heads_up([{"street": "preflop", "player": "A", "kind": "call", "to": 5}], kind="pokerstars")
    assert any("跟注后应累计" in e for e in r.errors)
    r = heads_up([{"street": "preflop", "player": "A", "kind": "raise", "to": 3}], kind="pokerstars")
    assert any("最小加注" in e for e in r.errors)
    r = heads_up([{"street": "preflop", "player": "A", "kind": "fold"}], players=[
        {"seat": 1, "name": "A", "stack": 100, "cards": ["Kd", "Kc"]}, {"seat": 2, "name": "B", "stack": 100}])
    assert any("牌张冲突" in e for e in r.errors)


def test_short_all_in_raise_does_not_reopen_betting():
    hand = {"hand_id": "manual-reopen", "source": {"kind": "pokerstars"}, "game": {"small_blind": 1, "big_blind": 2},
            "button_seat": 3, "players": [{"seat": 1, "name": "A", "stack": 1000}, {"seat": 2, "name": "B", "stack": 151},
                                          {"seat": 3, "name": "C", "stack": 1000}],
            "posts": [{"player": "A", "kind": "sb", "amount": 1}, {"player": "B", "kind": "bb", "amount": 2}],
            "actions": [{"street": "preflop", "player": "C", "kind": "call", "to": 2}, {"street": "preflop", "player": "A", "kind": "call", "to": 2},
                        {"street": "preflop", "player": "B", "kind": "check"}, {"street": "flop", "player": "A", "kind": "bet", "to": 100},
                        {"street": "flop", "player": "B", "kind": "raise", "to": 149, "all_in": True},
                        {"street": "flop", "player": "C", "kind": "call", "to": 149},
                        {"street": "flop", "player": "A", "kind": "raise", "to": 400}],
            "board": ["2c", "7d", "9h"]}
    r = replay(normalize(hand))
    assert any("没有重新开放加注" in e for e in r.errors)
    hand["actions"][-1] = {"street": "flop", "player": "A", "kind": "call", "to": 149}
    r = replay(normalize(hand))
    assert not any("重新开放" in e for e in r.errors)


def test_structural_problems_are_rejected_before_replay():
    hand = live_hand()
    with pytest.raises(ValueError, match="hand_id"):
        normalize({**hand, "hand_id": "bad id with spaces"})
    broken = copy.deepcopy(hand)
    broken["actions"][0].pop("to")
    with pytest.raises(ValueError, match="必须给出 to"):
        normalize(broken)
    with pytest.raises(ValueError, match="不在座位表"):
        normalize({**hand, "hero": "Nobody"})
    with pytest.raises(ValueError, match="无效牌张"):
        normalize({**hand, "board": ["Zz"]})


def three_blind(actions, **extra):
    from pokerlab.coach.live import build_live_hand
    spec = {"hand_id": "live-synthetic-3blind", "played_at": "2026-10-27", "hero": "Hero",
            "players": [{"position": "MB", "name": "Hero", "cards": ["Jx", "Jx"]}, {"position": "UTG", "name": "Alpha", "stack": 600}],
            "actions": actions}
    spec.update(extra)
    return normalize(build_live_hand(spec))


def test_three_blinds_fill_seats_posts_and_positions():
    hand = three_blind([{"street": "preflop", "player": "Alpha", "kind": "call"},
                    {"street": "preflop", "player": "#UTG+1", "kind": "call"},
                    {"street": "preflop", "player": "#LJ", "kind": "call"},
                    {"street": "preflop", "player": "#SB", "kind": "call"},
                    {"street": "preflop", "player": "Hero", "kind": "raise", "to": 90},
                    {"street": "preflop", "player": "Alpha", "kind": "raise", "to": 600, "all_in": True},
                    {"street": "preflop", "player": "Hero", "kind": "call"}],
                   board=["2c", "7d", "9h", "Ks", "3s"], showdown=[{"player": "Alpha", "cards": ["Qx", "Qx"]}])
    assert hand["game"]["preset"] == "live-5-5-10" and hand["game"]["middle_blind"] == 5 and hand["button_seat"] == 9
    assert [(p["kind"], p["player"], p["amount"]) for p in hand["posts"]] == [("sb", "#SB", 5), ("mb", "Hero", 5), ("bb", "#BB", 10)]
    r = replay(hand)
    assert r.errors == [] and r.complete and r.showdown
    assert r.positions["Hero"] == "MB" and r.positions["Alpha"] == "UTG" and r.positions["#BB"] == "BB"
    assert r.pot == 10 + 600 + 10 + 600 + 10 + 10
    assert not any("盲注与按钮" in w for w in r.warnings)
    seen = obs_set(hand, r)
    assert {("Alpha", "open_limp", True), ("Alpha", "three_bet", True), ("Hero", "fold_to_three_bet", False)} <= seen


def test_bomb_pot_starts_on_the_flop_and_gives_no_frequency_observations():
    hand = three_blind([{"street": "flop", "player": "Alpha", "kind": "bet", "to": 45},
                    {"street": "flop", "player": "Hero", "kind": "raise", "to": 200},
                    {"street": "flop", "player": "Alpha", "kind": "call"},
                    {"street": "turn", "player": "Hero", "kind": "check"}, {"street": "turn", "player": "Alpha", "kind": "check"},
                    {"street": "river", "player": "Hero", "kind": "bet", "to": 200}, {"street": "river", "player": "Alpha", "kind": "fold"}],
                   game={"bomb_pot": True}, board=["Ax", "3x", "7x", "5h", "Qx"], board_texture="翻牌两张红桃")
    assert hand["posts"] == [] and hand["game"]["bomb_pot"]
    r = replay(hand)
    assert r.errors == [] and r.complete and any("底注未知" in w for w in r.warnings)
    assert observations(hand, r) == [] and r.pot == 400 and r.returned == ("Hero", 200)
    wrong = three_blind([{"street": "preflop", "player": "Alpha", "kind": "call"}], game={"bomb_pot": True})
    assert any("此时不轮到" in e or "之后" in e for e in replay(wrong).errors)


def test_unknown_suits_skip_conflicts_but_rank_counts_are_checked():
    hand = live_hand()
    hand["players"][2]["cards"] = ["Kx", "Tx"]
    hand["showdown"] = [{"player": "Lee", "cards": ["Qx", "Jx"]}, {"player": "Kay", "cards": ["7x", "7x"]}]
    r = replay(normalize(hand))
    assert not any("牌张冲突" in e or "点数" in e for e in r.errors)
    hand["board"] = ["Ah", "7c", "2d", "7s", "Kd"]  # board 7c 7s + Kay 7x 7x = four sevens: still possible
    assert not any("点数" in e for e in replay(normalize(hand)).errors)
    hand["players"][3]["cards"] = ["7x", "2x"]  # a fifth seven
    assert any("同一点数超过 4 张" in e for e in replay(normalize(hand)).errors)


def test_unknown_positions_are_placed_by_action_order():
    from pokerlab.coach.live import build_live_hand_with_guesses
    spec = {"hand_id": "live-synthetic-unknown", "hero": "Hero",
            "players": [{"position": "+1", "name": "Villain"}, {"position": None, "name": "Hero", "cards": ["Jc", "Tc"]},
                        {"position": None, "name": "#limper2"}],
            "actions": [{"street": "preflop", "player": "Villain", "kind": "call"}, {"street": "preflop", "player": "#limper2", "kind": "call"},
                        {"street": "preflop", "player": "Hero", "kind": "raise", "to": 50},
                        {"street": "preflop", "player": "Villain", "kind": "call"}, {"street": "preflop", "player": "#limper2", "kind": "fold"},
                        {"street": "flop", "player": "Villain", "kind": "bet", "to": 75}, {"street": "flop", "player": "Hero", "kind": "call"}],
            "board": ["Qx", "7x", "3x"]}
    hand, guesses = build_live_hand_with_guesses(spec)
    assert guesses == ["Hero=HJ", "#limper2=LJ"] and hand["notes"].startswith("[系统] 位置未知")
    r = replay(normalize(hand))
    assert r.errors == [] and r.positions["Hero"] == "HJ"  # Villain leads into Hero, so Hero is not in the blinds


def test_fully_unknown_cards_and_structural_errors_surface_through_seating():
    from pokerlab.coach.live import build_live_hand_with_guesses
    hand = live_hand()
    hand["showdown"] = [{"player": "Lee", "cards": ["Qs", "??"]}, {"player": "Kay", "cards": ["7x", "xx"]}]
    r = replay(normalize(hand))
    assert r.errors == [] and normalize(hand)["showdown"][1]["cards"] == ["7x", "??"]
    spec = {"hand_id": "live-synthetic-bad", "players": [{"position": None, "name": "Hero", "cards": ["Zz", "Kd"]}],
            "actions": [{"street": "preflop", "player": "Hero", "kind": "call"}]}
    with pytest.raises(ValueError, match="无效牌张"):
        build_live_hand_with_guesses(spec)
