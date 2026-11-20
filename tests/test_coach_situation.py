"""Situation of a hand from its replay, and looking video hands up by situation (synthetic records only)."""
import json

import pytest

from pokerlab.coach import knowledge, situation, tools
from pokerlab.coach.hands import normalize, replay
from pokerlab.coach.store import CoachStore

SEATS = ("SB", "BB", "UTG", "HJ", "CO", "BTN")


def hand_of(actions, hero="BTN", board=(), cards=("Js", "Jc"), stacks=1000, posts=(), hand_id="h1", notes="1:00–2:00"):
    """``actions`` are 'street player kind [to]'; players are named after their seats and Hero sits at ``hero``."""
    name = lambda seat: "Hero" if seat == hero else seat
    stack = stacks if isinstance(stacks, dict) else dict.fromkeys(SEATS, stacks)
    players = [{"seat": i, "name": name(s), "stack": stack.get(s), "cards": list(cards) if s == hero else None} for i, s in enumerate(SEATS, 1)]
    moves = []
    for text in actions:
        street, player, kind, *to = text.split()
        moves.append({"street": street, "player": name(player), "kind": kind, **({"to": int(to[0])} if to else {})})
    return {"schema": "pokerlab-hand-v1", "hand_id": hand_id, "source": {"kind": "manual", "site": "test"}, "game": {"small_blind": 5, "big_blind": 10},
            "button_seat": 6, "players": players, "actions": moves, "board": list(board), "hero": "Hero", "notes": notes,
            "posts": [{"player": name("SB"), "kind": "sb", "amount": 5}, {"player": name("BB"), "kind": "bb", "amount": 10},
                      *[{"player": name(s), "kind": k, "amount": a} for s, k, a in posts]]}


def features(*args, **kwargs):
    hand = normalize(hand_of(*args, **kwargs))
    return situation.features(hand, replay(hand))


def test_combos_and_queries():
    assert situation.combo(["Js", "Jc"]) == "JJ" and situation.combo(["Ks", "As"]) == "AKs" and situation.combo(["Ks", "Ad"]) == "AKo"
    assert situation.combo(["Kx", "Qx"]) == "KQ" and situation.combo(["7x", "??"]) is None and situation.combo(None) is None
    assert situation.holds("AKs", "AK") and situation.holds("AKo", "ka") and situation.holds("AK", "AK")
    assert not situation.holds("AKo", "AKs") and not situation.holds("AK", "AKs")  # unknown suits never count as suited
    assert situation.holds("A5s", "Axs") and situation.holds("JJ", "Jx") and situation.holds("T9s", "10 9s".replace(" ", ""))
    assert not situation.holds("A5o", "Axs") and not situation.holds("JJ", "Jxs") and not situation.holds(None, "JJ")
    with pytest.raises(ValueError, match="牌型"):
        situation.holds("JJ", "A♠K♠")


@pytest.mark.parametrize("board, present, absent", [
    (["Ah", "7h", "2h"], {"A_high", "monotone"}, {"rainbow", "dry", "wet"}),
    (["9d", "8c", "7h"], {"low", "rainbow", "connected"}, {"dry", "paired"}),
    (["Js", "7h", "7c"], {"J_high", "paired", "rainbow", "dry"}, {"connected"}),
    (["Th", "9h", "6c"], {"T_high", "two_tone", "connected", "wet"}, {"dry"}),
    (["Ah", "2d", "3c"], {"A_high", "connected", "rainbow"}, {"dry"}),   # the wheel
    (["Kx", "Kd", "4c"], {"K_high", "paired"}, {"rainbow", "two_tone", "monotone", "dry"}),  # a suit is unknown
    (["5s", "5d", "5c"], {"low", "trips"}, {"paired"}),
])
def test_board_tags(board, present, absent):
    tags = situation.board_tags(board)
    assert present <= tags and not absent & tags


def test_flop_not_seen_has_no_board_tags():
    assert situation.board_tags([]) == set() and situation.board_tags(["Ah", "7h"]) == set() and situation.board_tags(["Ah", "7h", "??"]) == set()


@pytest.mark.parametrize("actions, pot, line, facing", [
    (["preflop Hero raise 30", "preflop BB call"], {"single_raised"}, {"preflop:open"}, set()),
    (["preflop UTG call", "preflop Hero raise 40", "preflop BB fold"], {"single_raised", "iso"}, {"preflop:iso"}, set()),
    (["preflop UTG raise 30", "preflop Hero raise 90", "preflop UTG call"], {"3bet"}, {"preflop:3bet"}, {"preflop:open"}),
    (["preflop UTG raise 30", "preflop HJ call", "preflop Hero raise 120", "preflop UTG fold", "preflop HJ call"],
     {"3bet", "squeeze"}, {"preflop:squeeze"}, {"preflop:open"}),
    (["preflop Hero raise 30", "preflop SB raise 100", "preflop Hero call"], {"3bet"}, {"preflop:open", "preflop:call_3bet", "preflop:call"}, {"preflop:3bet"}),
    (["preflop Hero raise 30", "preflop SB raise 100", "preflop Hero raise 250", "preflop SB call"], {"4bet"}, {"preflop:open", "preflop:4bet"}, {"preflop:3bet"}),
    (["preflop UTG raise 30", "preflop HJ raise 100", "preflop CO raise 250", "preflop Hero fold"], {"4bet"}, {"preflop:fold", "preflop:fold_4bet"}, {"preflop:4bet"}),
    (["preflop UTG raise 30", "preflop Hero raise 100", "preflop SB raise 250", "preflop UTG raise 600", "preflop Hero fold"], {"5bet"}, {"preflop:3bet", "preflop:fold_5bet"}, {"preflop:5bet"}),
    (["preflop UTG raise 30", "preflop HJ call", "preflop CO raise 120", "preflop Hero call"], {"3bet", "squeeze"}, {"preflop:call_3bet"}, {"preflop:squeeze"}),
    (["preflop UTG call", "preflop Hero call", "preflop BB check"], {"limped"}, {"preflop:limp"}, set()),
])
def test_preflop_situation(actions, pot, line, facing):
    f = features(actions)
    assert pot <= f["pot"] and line <= f["line"] and facing <= f["facing"]
    assert not {"squeeze"} & f["pot"] or "squeeze" in pot


def test_limper_called_raise_is_call_open():
    f = features(["preflop Hero call", "preflop BB raise 40", "preflop Hero call"], hero="UTG")
    assert {"preflop:limp", "preflop:call_open"} <= f["line"] and "preflop:iso" in f["facing"] and "iso" in f["pot"]


def test_decision_at_the_end_of_the_record_counts_as_faced():
    """Teaching spots stop where Hero has to decide; that decision is what the spot is about."""
    assert "preflop:3bet" in features(["preflop Hero raise 30", "preflop SB raise 100"])["facing"]
    assert "preflop:squeeze" in features(["preflop UTG raise 30", "preflop HJ call", "preflop CO raise 120"])["facing"]
    spot = features(["preflop Hero raise 30", "preflop BB call", "flop BB check", "flop Hero bet 20", "flop BB raise 80"], board=["9h", "8d", "2c"])
    assert {"flop:raise", "flop:check_raise"} <= spot["facing"]
    river = features(["preflop Hero raise 30", "preflop BB call", "flop BB check", "flop Hero check", "turn BB check", "turn Hero check", "river BB bet 970"],
                     board=["9h", "8d", "2c", "3s", "Kd"])
    assert {"river:bet", "river:all_in"} <= river["facing"]
    folded = features(["preflop Hero raise 30", "preflop SB raise 100", "preflop Hero fold"])
    assert "preflop:fold_3bet" in folded["line"]
    over = features(["preflop UTG raise 30", "preflop Hero fold", "preflop BB raise 100"])  # Hero is out by the time of the 3bet
    assert "preflop:3bet" not in over["facing"]


def test_postflop_line_position_and_depth():
    f = features(["preflop Hero raise 30", "preflop BB call", "flop BB check", "flop Hero bet 20", "flop BB raise 80", "flop Hero call",
                  "turn BB bet 200", "turn Hero fold"], board=["9h", "8d", "2c", "3s"])
    assert {"flop:cbet", "flop:bet_call", "flop:bet", "flop:call", "turn:fold"} <= f["line"]
    assert {"flop:raise", "flop:check_raise", "turn:bet"} <= f["facing"] and "flop:bet" not in f["facing"]
    assert f["in_position"] is True and f["multiway"] is False and f["players_to_flop"] == 2 and f["rivals"] == ["BB"] and f["depth_bb"] == 100

    caller = features(["preflop BTN raise 30", "preflop Hero call", "flop Hero bet 20", "flop BTN fold"], hero="BB", board=["9h", "8d", "2c"])
    assert "flop:donk" in caller["line"] and "flop:cbet" not in caller["line"] and caller["in_position"] is False

    barrel = features(["preflop Hero raise 30", "preflop BB call", "flop BB check", "flop Hero bet 20", "flop BB call", "turn BB check", "turn Hero bet 60", "turn BB fold"],
                      board=["9h", "8d", "2c", "3s"])
    assert {"flop:cbet", "turn:cbet"} <= barrel["line"]

    delayed = features(["preflop Hero raise 30", "preflop BB call", "flop BB check", "flop Hero check", "turn BB bet 40", "turn Hero raise 120", "turn BB fold"],
                       board=["9h", "8d", "2c", "3s"], hero="BTN")
    assert "turn:donk" not in delayed["line"] and "turn:raise" in delayed["line"]

    raise_check = features(["preflop BTN raise 30", "preflop Hero call", "flop Hero check", "flop BTN bet 20", "flop Hero raise 80", "flop BTN call"],
                           hero="BB", board=["9h", "8d", "2c"])
    assert {"flop:check_raise", "flop:check", "flop:raise"} <= raise_check["line"]

    multi = features(["preflop UTG raise 30", "preflop CO call", "preflop Hero call"], board=["9h", "8d", "2c"])
    assert multi["multiway"] is None  # no flop actions and the record stops before the flop
    three = features(["preflop UTG raise 30", "preflop CO call", "preflop Hero call", "preflop SB fold", "preflop BB fold", "flop UTG check", "flop CO check", "flop Hero check"],
                     board=["9h", "8d", "2c"])
    assert three["multiway"] is True and three["players_to_flop"] == 3 and three["in_position"] is True and three["rivals"] == ["CO", "UTG"]


def test_depth_unit_unknown_stacks_and_positions():
    assert features(["preflop Hero raise 60", "preflop BB call"], stacks={**dict.fromkeys(SEATS, 2000), "BB": 800})["depth_bb"] == 80
    straddled = features(["preflop UTG call", "preflop Hero raise 80", "preflop UTG call"], posts=[("HJ", "straddle", 20)], stacks=1000)
    assert straddled["depth_bb"] == 50  # the straddle is the unit in a straddled game
    assert features(["preflop Hero raise 30", "preflop BB call"], stacks={**dict.fromkeys(SEATS, 1000), "BB": None})["depth_bb"] is None
    assert features(["preflop Hero raise 30", "preflop BB call"], stacks={"BB": 1000})["depth_bb"] is None
    assert features(["preflop Hero raise 30"], stacks={"BTN": 1000, "BB": 500})["depth_bb"] is None  # others unknown, so the depth is too
    assert {"UTG", "LJ", "EP", "MP"} == features(["preflop Hero raise 30"], hero="UTG")["positions"]  # HHP names the first of six seats LJ
    assert situation.position_tags("UTG", 9) == {"UTG", "EP"} and situation.position_tags("LJ", 9) == {"LJ", "EP", "MP"}
    assert situation.position_tags("BB", 6) == {"BB", "blinds"} and situation.position_tags(None, 6) == set()


def test_no_hero_has_no_situation():
    raw = hand_of(["preflop UTG raise 30"])
    raw["hero"] = None
    raw["players"] = [{**p, "name": p["name"].replace("Hero", "BTN")} for p in raw["players"]]
    hand = normalize(raw)
    assert situation.features(hand, replay(hand)) is None


@pytest.fixture()
def base(tmp_path, monkeypatch):
    (tmp_path / "captions").mkdir()
    (tmp_path / "hands").mkdir()
    (tmp_path / "channel_videos_utf8.tsv").write_text("videoA00001\t600\t10\tVideo A\nvideoB00002\t600\t10\tVideo B\n", encoding="utf-8")
    jj = hand_of(["preflop UTG raise 30", "preflop HJ call", "preflop CO raise 120", "preflop Hero call"], hand_id="a-jj-squeeze", notes="1:00–2:00 讲解人思路：阻断牌很重要")
    jj2 = hand_of(["preflop Hero raise 30", "preflop BB call", "flop BB check", "flop Hero bet 20", "flop BB raise 80", "flop Hero fold"], board=["9h", "8d", "2c"],
                  hand_id="a-jj-srp", notes="3:00–4:00 讲解人思路：翻牌弃牌")
    jj3 = hand_of(["preflop Hero raise 30", "preflop BB call"], hand_id="a-jj-3", notes="5:00–6:00")
    jj4 = hand_of(["preflop Hero raise 30", "preflop BB call"], hand_id="a-jj-4", notes="7:00–8:00")
    ak = hand_of(["preflop UTG raise 30", "preflop Hero raise 90"], cards=("As", "Kd"), hand_id="b-ak", hero="HJ", stacks=4000, notes="1:00–2:00")
    unknown = hand_of(["preflop Hero raise 30", "preflop BB call"], cards=("Qs", "Qd"), hand_id="b-qq", stacks={}, notes="3:00–4:00")
    (tmp_path / "hands" / "videoA00001.json").write_text(json.dumps({"video_id": "videoA00001", "hands": [jj, jj2, jj3, jj4]}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "hands" / "videoB00002.json").write_text(json.dumps(
        {"video_id": "videoB00002", "hands": [ak, unknown], "partial": [{"label": "PLO 双板 bomb pot（5:00–6:00）", "known": {"time": "5:00–6:00", "note": "四张底牌"}, "missing": ["格式不支持"]}]},
        ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("POKERLAB_KNOWLEDGE_HOME", str(tmp_path))
    return knowledge.Knowledge(tmp_path)


def test_find_orders_by_criteria_met_and_says_what_is_missed(base):
    found = base.find({"cards": ["JJ"], "pot_type": ["squeeze"], "facing": ["preflop:squeeze"]})
    assert found["exact_total"] == 1 and found["exact_by_video"] == {"videoA00001": 1}
    first = found["results"][0]
    assert first["record"] == "a-jj-squeeze" and first["missed"] == [] and first["matched"] == ["cards:JJ", "pot_type:squeeze", "facing:preflop:squeeze"]
    assert first["title"] == "Video A" and first["time"] == ["1:00–2:00"] and first["url"].endswith("&t=60s") and first["reasoning"].startswith("讲解人思路")
    assert first["hero_position"] == "BTN" and first["hero_cards"] == ["Js", "Jc"] and first["depth_bb"] == 100 and "squeeze" in first["pot_type"]
    assert "CO 加注到 120" in first["actions"]
    near = found["results"][1]
    assert near["record"].startswith("a-jj") and near["matched"] == ["cards:JJ"] and "pot_type:squeeze" in near["missed"]


def test_find_filters(base):
    assert [r["record"] for r in base.find({"cards": ["AKo"], "position": ["MP"]})["results"][:1]] == ["b-ak"]
    assert base.find({"cards": ["AK"]})["exact_total"] == 1 and base.find({"cards": ["Ax"]})["exact_total"] == 1 and base.find({"cards": ["AKs"]})["exact_total"] == 0
    assert base.find({"depth_min_bb": 300})["exact_total"] == 1 and base.find({"depth_max_bb": 150})["exact_total"] == 4
    assert base.find({"line": ["flop:bet_fold", "flop:cbet"], "facing": ["flop:check_raise"]})["exact_total"] == 1
    assert base.find({"board": ["low", "rainbow"]})["exact_total"] == 1 and base.find({"board": ["low", "monotone"]})["exact_total"] == 0
    assert base.find({"in_position": True, "multiway": False})["exact_total"] == 1
    assert base.find({"opponent_position": ["BB"]})["exact_total"] == 4
    assert base.find({"cards": ["JJ"], "video_id": "videoB00002"})["results"] == []
    with pytest.raises(ValueError, match="至少给一个条件"):
        base.find({})
    with pytest.raises(ValueError, match="牌型"):
        base.find({"cards": ["AsKs"]})


def test_find_unknown_never_matches_and_text_reaches_partials(base):
    assert "b-qq" not in [r["record"] for r in base.find({"depth_min_bb": 0, "cards": ["JJ"]}, 20)["results"] if not r["missed"]]
    assert base.find({"depth_min_bb": 0})["exact_total"] == 5  # the sixth hand has no known stacks
    found = base.find({"text": "阻断"})
    assert found["exact_total"] == 1 and found["results"][0]["record"] == "a-jj-squeeze" and found["results"][0]["matched"] == ["text:阻断"]
    [partial] = base.find({"text": "bomb"})["results"]
    assert partial["complete"] is False and partial["missing"] == ["格式不支持"] and partial["time"] == ["5:00–6:00"]
    assert base.find({"text": "bomb 四张"})["exact_total"] == 1 and base.find({"text": "bomb 五张"})["exact_total"] == 0


def test_find_keeps_several_videos_in_view(base):
    found = base.find({"pot_type": ["single_raised"]}, 20)
    assert found["exact_total"] == 4 and found["exact_by_video"]["videoA00001"] == 3
    assert sum(r["video_id"] == "videoA00001" for r in found["results"]) == 3  # the rest are reached with video_id
    assert len(base.find({"pot_type": ["single_raised"], "video_id": "videoA00001"}, 20)["results"]) == 3
    assert len(base.find({"cards": ["JJ"]}, 2)["results"]) == 2


def test_tool_finds_hands_like_a_users_hand(base, tmp_path):
    store = CoachStore(tmp_path / "coach")
    mine = hand_of(["preflop Hero raise 30", "preflop BB call", "flop BB check", "flop Hero bet 20", "flop BB raise 80", "flop Hero fold"], board=["9s", "8d", "3c"],
                   stacks=1200, hand_id="my-hand-1", notes="现场")
    mine = normalize(mine)
    store.add_hand(mine, "agent")
    found = tools.execute(store, "find_hhp_hands", {"similar_to": "my-hand-1"})
    assert found["results"][0]["record"] == "a-jj-srp" and "不是 Solver" in found["note"]
    assert found["criteria"]["cards"] == "JJ" and found["criteria"]["position"] == "BTN" and found["criteria"]["pot_type"] == ["single_raised"]
    assert "flop:bet_fold" in found["criteria"]["line"] and "flop:bet" not in found["criteria"]["line"] and "preflop:raise" not in found["criteria"]["line"]
    assert found["criteria"]["depth_min_bb"] == 84 and found["criteria"]["depth_max_bb"] == 168
    narrowed = tools.execute(store, "find_hhp_hands", {"similar_to": "my-hand-1", "cards": ["AK"], "limit": 1})
    assert narrowed["criteria"]["cards"] == ["AK"] and len(narrowed["results"]) == 1
    with pytest.raises(ValueError, match="手牌不存在"):
        tools.execute(store, "find_hhp_hands", {"similar_to": "nope"})
    assert tools.execute(store, "find_hhp_hands", {"cards": ["JJ"]})["exact_total"] == 4
    assert "find_hhp_hands" in tools.NAMES
