"""Append-only coach store, Beta-binomial statistics and the agent-facing coach tools."""
import json
from pathlib import Path

import pytest
from scipy.stats import beta

from pokerlab.coach import tools
from pokerlab.coach.stats import load_priors, player_type, posterior, profile, tags
from pokerlab.coach.evidence import NEEDS_EVERY_HAND, Observation
from pokerlab.coach.store import CoachStore
from tests.test_coach_hands import DATA, live_hand


def test_posterior_math_score_and_tags():
    post = posterior(7, 8, 0.45, 10)
    assert post["mean"] == pytest.approx((4.5 + 7) / 18)
    assert post["ci90"] == pytest.approx(list(beta.ppf([0.05, 0.95], 11.5, 6.5)))
    assert post["score"] == round(10 * beta.sf(0.45, 11.5, 6.5)) and post["score"] >= 9
    assert posterior(0, 0, 0.45, 10)["score"] == 5 and posterior(0, 0, 0.45, 10)["raw"] is None
    assert posterior(0, 0, 0.06, 10)["score"] == 5  # no evidence, whatever the prior's skew says
    priors = load_priors()
    assert priors["calibrated"] is False
    one = [Observation("fold_to_river_bet", "V", "h1", True, "river")]
    assert tags(profile(one, priors), priors) == []  # one hand never makes a tag
    many = [Observation("fold_to_river_bet", "V", f"h{i}", i < 9, "river") for i in range(10)]
    found = tags(profile(many, priors), priors)
    assert found[0]["stat"] == "fold_to_river_bet" and found[0]["direction"] == "high" and found[0]["n"] == 10
    assert "h8" in found[0]["evidence"] and player_type(profile(many, priors))["type"] == "未定"


def test_a_tag_needs_three_different_hands():
    priors = load_priors()
    streets = ("flop", "turn", "river")
    one_hand = [Observation("aggression", "V", "h1", True, street) for street in streets]
    assert profile(one_hand, priors)["aggression"]["p_above_population"] > 0.85  # the rate alone would pass
    assert tags(profile(one_hand, priors), priors) == []
    two_hands = one_hand + [Observation("aggression", "V", "h2", True, street) for street in streets]
    assert tags(profile(two_hands, priors), priors) == []
    three_hands = two_hands + [Observation("aggression", "V", "h3", True, street, selected=True) for street in streets]
    found = tags(profile(three_hands, priors), priors)
    assert found[0]["stat"] == "aggression" and found[0]["hands"] == 3 and found[0]["selected_hands"] == 1


def test_live_notes_do_not_feed_rates_that_need_every_hand(tmp_path):
    store = CoachStore(tmp_path)
    store.add_hand(live_hand(), "agent")
    store.confirm("live-20261029-straddle", 1)
    kay = store.player_profile("Kay")
    assert {name: kay["stats"][name]["n"] for name in NEEDS_EVERY_HAND} == dict.fromkeys(NEEDS_EVERY_HAND, 0)
    assert kay["stats"]["aggression"]["n"] == 2 and kay["stats"]["aggression"]["selected_hands"] == 1
    assert kay["selected_hands"] == 1 and "笔记" in kay["sample_note"]
    row = next(p for p in store.players() if p["player"] == "Kay")
    assert row["vpip"] is None and row["type"] == "未定"
    store.import_text((DATA / "pokerstars_synthetic.txt").read_text(encoding="utf-8"))
    mike = store.player_profile("mike")
    assert mike["stats"]["vpip"]["n"] == 3 and mike["hands"] == 5 and mike["selected_hands"] == 1  # the live hand adds no VPIP


def test_import_confirms_and_profiles_from_confirmed_hands(tmp_path):
    store = CoachStore(tmp_path)
    results = store.import_text((DATA / "pokerstars_synthetic.txt").read_text(encoding="utf-8"))
    assert [r["result"] for r in results] == ["stored"] * 4 and all(r["status"] == "confirmed" for r in results)
    again = store.import_text((DATA / "pokerstars_synthetic.txt").read_text(encoding="utf-8"))
    assert [r["result"] for r in again] == ["duplicate"] * 4
    mike = store.player_profile("mike")
    assert mike["hands"] == 4 and mike["stats"]["vpip"]["n"] == 3 and mike["stats"]["vpip"]["k"] == 3
    assert mike["priors"]["calibrated"] is False and mike["showdowns"][0]["cards"] == ["Jc", "Td"]
    files = sorted(p.name for p in tmp_path.glob("hands/*/r*.json"))
    assert files == ["r0001.json"] * 4


def test_live_hands_need_user_confirmation_and_revisions_are_append_only(tmp_path):
    store = CoachStore(tmp_path)
    status = store.add_hand(live_hand(), "agent")
    assert status["status"] == "pending" and status["latest_revision"] == 1
    assert store.player_profile("Kay")["hands"] == 0 and store.player_profile("Kay")["pending_hands"] == ["live-20261029-straddle"]
    store.confirm("live-20261029-straddle", 1)
    assert store.player_profile("Kay")["stats"]["aggression"]["k"] == 1
    changed = live_hand()
    changed["notes"] = "第二次整理"
    status = store.add_hand(changed, "agent")
    assert status["status"] == "new_revision" and status["confirmed_revision"] == 1
    assert store.player_profile("Kay")["hands"] == 1  # stats keep using the confirmed revision
    broken = live_hand()
    broken["actions"][3] = {"street": "flop", "player": "Hero", "kind": "call"}  # nothing to call
    status = store.add_hand(broken, "agent")
    assert status["status"] == "new_revision" and status["errors"]
    with pytest.raises(ValueError, match="有错误"):
        store.confirm("live-20261029-straddle", status["latest_revision"])
    folder = next(tmp_path.glob("hands/live-20261029-straddle-*"))
    assert sorted(p.name for p in folder.iterdir()) == ["r0001.json", "r0002.json", "r0003.json"]
    first = json.loads((folder / "r0001.json").read_text(encoding="utf-8"))
    assert first["hand"]["notes"] is None  # the original file was not rewritten


def test_aliases_hero_notes_and_reload(tmp_path):
    store = CoachStore(tmp_path)
    store.import_text((DATA / "pokerstars_synthetic.txt").read_text(encoding="utf-8"))
    store.add_hand({**live_hand(), "players": [{**p, "name": "Mikey"} if p["name"] == "Mike" else p for p in live_hand()["players"]],
                    "posts": [{**p, "player": "Mikey"} if p["player"] == "Mike" else p for p in live_hand()["posts"]]}, "agent")
    store.confirm("live-20261029-straddle", 1)
    assert store.player_profile("Mike")["hands"] == 4
    store.link_alias("Mikey", "Mike")
    assert store.player_profile("Mikey")["hands"] == 5 and store.player_profile("Mike")["aliases"] == ["Mike", "Mikey"]
    store.set_hero(["Hero"])
    with pytest.raises(ValueError, match="至少一手"):
        store.add_note("Mike", "河牌下注偏价值", [], "agent")
    store.add_note("Mike", "河牌下注偏价值", ["ps-250000000002"], "agent")
    reopened = CoachStore(tmp_path)
    profile = reopened.player_profile("mikey")
    assert profile["hands"] == 5 and profile["notes"][0]["hand_ids"] == ["ps-250000000002"]
    players = {p["key"]: p for p in reopened.players()}
    assert players["hero"]["is_hero"] and "mikey" not in players
    assert reopened.load_warnings == []


def test_coach_tools_dispatch(tmp_path):
    store = CoachStore(tmp_path)
    imported = tools.execute(store, "import_hand_history", {"text": (DATA / "pokerstars_synthetic.txt").read_text(encoding="utf-8")})
    assert imported["imported"] == 4 and imported["rejected"] == 0
    recorded = tools.execute(store, "record_live_hand", {"hand": live_hand()})
    assert recorded["status"] == "pending" and "确认" in recorded["next_step"] and recorded["replay"]["inferred_actions"] == 3
    rejected = tools.execute(store, "import_hand_history", {"text": "this is not a hand history at all"})
    assert rejected["rejected"] == 1
    assert {p["key"] for p in tools.execute(store, "list_players", {})["players"]} >= {"mike", "hero"}
    assert len(tools.execute(store, "list_hands", {"status": "pending"})["hands"]) == 1
    detail = tools.execute(store, "get_hand", {"hand_id": "ps-250000000002"})
    assert detail["replay"]["showdown"] and detail["observations"]
    assert "confirm_hand" not in tools.NAMES  # the assistant cannot confirm hands
    with pytest.raises(ValueError):
        tools.execute(store, "unknown_tool", {})


def test_levels_context_observations_and_anonymous_seats(tmp_path):
    from tests.test_coach_hands import three_blind
    store = CoachStore(tmp_path)
    assert store.settings()["default_game"] == "live-5-5-10" and "MB 5" in store.settings()["default_game_label"]
    with pytest.raises(ValueError, match="未知级别"):
        store.set_default_game("nope")
    store.set_default_game("live-2-5")
    assert CoachStore(tmp_path).default_game() == "live-2-5"
    store.set_default_game("live-5-5-10")
    hand = three_blind([{"street": "preflop", "player": "Alpha", "kind": "raise", "to": 35},
                    {"street": "preflop", "player": "Hero", "kind": "call"}, {"street": "preflop", "player": "#BB", "kind": "fold"},
                    {"street": "flop", "player": "Hero", "kind": "check"}, {"street": "flop", "player": "Alpha", "kind": "bet", "to": 40},
                    {"street": "flop", "player": "Hero", "kind": "fold"}], board=["Qx", "7x", "3x"])
    store.add_hand(hand, "agent")
    store.add_note("Alpha", "水下，VPIP 不太高，很多 limp", [], "agent", "observation", "read", "2026-10-27")
    with pytest.raises(ValueError, match="推断必须引用"):
        store.add_note("Alpha", "他喜欢慢打", [], "agent", "inference")
    context = store.context()
    alpha = next(p for p in context["players"] if p["key"] == "alpha")
    assert alpha["pending_hands"] == 1 and alpha["notes"] == 1 and "VPIP" in alpha["recent_notes"][0]
    assert not any(p["key"].startswith("#") for p in context["players"])
    store.confirm(hand["hand_id"], 1)
    keys = {p["key"] for p in store.players()}
    assert keys == {"alpha", "hero"}
    profile = store.player_profile("Alpha")
    assert profile["stats"]["cbet_flop"]["k"] == 1 and profile["notes"][0]["kind"] == "observation"


def test_position_based_live_hand_through_the_tool(tmp_path):
    store = CoachStore(tmp_path)
    spec = {"hand_id": "live-synthetic-tool", "hero": "Hero", "players": [{"position": "+1", "name": "Villain"}, {"position": "MB", "name": "Hero", "cards": ["Jc", "Tc"]}],
            "actions": [{"street": "preflop", "player": "Villain", "kind": "call"}, {"street": "preflop", "player": "Hero", "kind": "raise", "to": 50},
                        {"street": "preflop", "player": "Villain", "kind": "call"}, {"street": "flop", "player": "Villain", "kind": "bet", "to": 75},
                        {"street": "flop", "player": "Hero", "kind": "call"}, {"street": "turn", "player": "Villain", "kind": "bet", "to": 125},
                        {"street": "turn", "player": "Hero", "kind": "fold"}], "board": ["Qx", "7x", "3x", "Qx"], "board_texture": "翻牌彩虹"}
    result = tools.execute(store, "record_live_hand", {"hand": spec})
    assert result["status"] == "pending" and result["errors"] == []
    detail = tools.execute(store, "get_hand", {"hand_id": "live-synthetic-tool"})
    assert detail["replay"]["positions"]["Villain"] == "UTG+1" and detail["replay"]["positions"]["Hero"] == "MB"
    assert tools.execute(store, "get_review_context", {})["default_game"] == "live-5-5-10"
    linked = tools.execute(store, "link_player_alias", {"name": "对手丙", "target": "Villain"})
    assert linked["resolves_to"] == "villain"
    note = tools.execute(store, "add_player_note", {"player": "对手丙", "text": "和别人谈笑风生，然后很快跟注", "kind": "observation", "topic": "tell",
                                                    "session": "2026-10-27", "hand_ids": ["live-synthetic-tool"]})
    assert note["player"] == "villain"


def test_equity_against_known_values():
    from pokerlab.coach.equity import equity, expand
    assert len(expand("AKo")) == 12 and len(expand("AKs")) == 4 and len(expand("QQ")) == 6 and len(expand("AK")) == 16
    aa = equity(["Ah", "Ad"], ["7c2d"], boards=8000)
    assert abs(aa["equity"] - 0.88) < 0.015  # published AA vs 72o is about 88%
    jj = equity(["Js", "Jh"], ["QQ"], boards=2000)
    assert abs(jj["equity"] - 0.18) < 0.02 and jj["combos"] == 6


def test_equity_from_a_known_board_is_exact():
    from pokerlab.coach.equity import equity
    turn = equity(["Ad", "Jd"], ["AhKs"], board=["Ac", "6c", "7h", "3h"])
    assert turn["equity"] == pytest.approx(3 / 44) and turn["method"] == "enumerated" and turn["std_error"] == 0  # three jacks
    river = equity(["Ad", "Jd"], ["AhKs", "7d7s"], board=["Ac", "6c", "7h", "3h", "2s"])
    assert river["equity"] == 0
    chop = equity(["Ad", "Ks"], ["AhKh"], board=["2c", "3d", "7h", "9s", "Jc"])
    assert chop["equity"] == 0.5
    flop = equity(["Jh", "Jd"], [("QsQd", 1.0), ("2s2d", 0.5)], board=["Jc", "7h", "3c"])
    assert 0.9 < flop["equity"] < 1 and flop["combos"] == 1.5
    with pytest.raises(ValueError, match="重复"):
        equity(["Ad", "Jd"], ["QQ"], board=["Ad", "6c", "7h"])
    with pytest.raises(ValueError, match="冲突"):
        equity(["Ad", "Jd"], ["AdKs"], board=["2c", "3d", "7h"])


@pytest.mark.parametrize("text, expected", [
    ("QQ+", ["QQ", "KK", "AA"]), ("TT-88", ["88", "99", "TT"]), ("ATs+", ["ATs", "AJs", "AQs", "AKs"]), ("A4s-A2s", ["A2s", "A3s", "A4s"]),
    ("KQo", ["KQo"]), ("AK", ["AK"]), ("AhKh", ["AhKh"]),
])
def test_range_text(text, expected):
    from pokerlab.coach.equity import parse_range
    assert [name for name, _ in parse_range(text)] == expected


def test_range_text_weights_and_bad_entries():
    from pokerlab.coach.equity import parse_range
    assert parse_range("AQo:0.5, JJ") == [("AQo", 0.5), ("JJ", 1.0)]
    with pytest.raises((ValueError, IndexError)):
        parse_range("ZZ")


def test_equity_tool(tmp_path):
    store = CoachStore(tmp_path)
    found = tools.execute(store, "calc_equity", {"hero": ["Ad", "Jd"], "villain": "AK,AQ", "board": ["Ac", "6c", "7h", "3h"]})
    assert found["equity"] == pytest.approx(0.0653, abs=0.001) and found["combos"] == 16 and found["by_hand_total"] == 2
    allin = tools.execute(store, "calc_equity", {"hero": ["Jh", "Js"], "villain": "QQ+,AK,AQ"})
    assert abs(allin["equity"] - 0.426) < 0.01 and allin["method"] == "monte_carlo"
    with pytest.raises(ValueError, match="0、3、4"):
        tools.execute(store, "calc_equity", {"hero": ["Ad", "Jd"], "villain": "QQ", "board": ["Ac", "6c"]})


def test_a_live_hand_that_does_not_replay_is_not_kept(tmp_path):
    store = CoachStore(tmp_path)
    broken = {"hand_id": "live-broken", "played_at": "2026-10-27", "players": [{"position": "UTG", "name": "Carl", "stack": None}, {"position": "LJ", "name": "Hero", "stack": None}],
              "actions": [{"street": "flop", "player": "Carl", "kind": "check"}, {"street": "flop", "player": "Hero", "kind": "check"}], "board": ["Ax", "Qx", "Tx"], "hero": "Hero"}
    result = tools.execute(store, "record_live_hand", {"hand": broken})
    assert result["result"] == "not_stored" and result["errors"] and "没有保存" in result["next_step"]
    assert store.list_hands() == [] and not list(tmp_path.glob("hands/*"))
    unknown = dict(broken, actions=[{"street": "preflop", "player": "Carl", "kind": "raise", "to": None}])
    result = tools.execute(store, "record_live_hand", {"hand": unknown})
    assert result["result"] == "not_stored" and "必须给出 to" in result["errors"][0] and not list(tmp_path.glob("hands/*"))
