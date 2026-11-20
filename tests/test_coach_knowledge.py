"""Knowledge-base chunking and search on synthetic caption files (no real video data in tests)."""
import json

import pytest

from pokerlab.coach import knowledge, tools
from pokerlab.coach.store import CoachStore


def caption(path, lines):
    events = [{"tStartMs": int(t * 1000), "dDurationMs": 2000, "segs": [{"utf8": text}]} for t, text in lines]
    path.write_text(json.dumps({"events": events}), encoding="utf-8")


@pytest.fixture()
def base(tmp_path, monkeypatch):
    (tmp_path / "captions").mkdir()
    caption(tmp_path / "captions" / "vidAAAAAAA1.en.json3",
            [(0, "welcome back"), (10, "today we talk about pocket jacks"), (30, "when a tight player limp re-raises you"),
             (65, "their range is usually queens kings aces"), (90, "so jacks should often fold"), (130, "next topic river bluffs")])
    caption(tmp_path / "captions" / "vidBBBBBBB2.en.json3",
            [(0, "multiway pots need value in every pot"), (40, "do not bluff three players"), (80, "check raise on the turn")])
    (tmp_path / "channel_videos_utf8.tsv").write_text("vidAAAAAAA1\t600\t10\tWhy Jacks Are Hard\nvidBBBBBBB2\t300\t5\tMultiway Basics\n", encoding="utf-8")
    monkeypatch.setenv("POKERLAB_KNOWLEDGE_HOME", str(tmp_path))
    return knowledge.Knowledge(tmp_path)


def test_chunks_titles_and_search_ranking(base):
    assert base.stats()["videos"] == 2 and len(base.chunks) == 5  # 0-59s, 65s, 130s | 0-59s, 80s
    hits = base.search("limp reraise jacks range")
    assert hits[0]["video_id"] == "vidAAAAAAA1" and hits[0]["title"] == "Why Jacks Are Hard"
    assert hits[0]["url"].endswith("&t=0s") or hits[0]["url"].endswith("&t=65s")
    assert base.search("multi-way bluff")[0]["video_id"] == "vidBBBBBBB2"
    assert knowledge.tokens("Three-bet and c-bet, check-raise") == ["3bet", "cbet", "checkraise"]
    assert base.search("zzzz nothing") == []
    weak = base.search("bomb pot")  # only "pot" exists in the captions
    assert weak and weak[0]["missing"] == ["bomb"] and weak[0]["matched"] == ["pot"]


def test_read_window_and_tools(base, tmp_path):
    window = base.read("vidAAAAAAA1", 60, 40)
    assert "queens kings aces" in window["text"] and "river" not in window["text"] and window["start"] == "1:00"
    with pytest.raises(ValueError):
        base.read("missing", 0)
    store = CoachStore(tmp_path / "coach")
    found = tools.execute(store, "search_hhp", {"query": "limp reraise jacks"})
    assert found["results"] and found["knowledge_base"]["videos"] == 2 and "不是 Solver" in found["note"]
    assert "jacks" in tools.execute(store, "read_hhp", {"video_id": "vidAAAAAAA1", "start_seconds": 0, "seconds": 60})["text"]


def hand_record(hand_id, notes):
    return {"schema": "pokerlab-hand-v1", "hand_id": hand_id, "source": {"kind": "manual", "site": "HHP video vidAAAAAAA1"},
            "game": {"small_blind": 5, "big_blind": 10}, "button_seat": 3,
            "players": [{"seat": 1, "name": "SB", "stack": 1000}, {"seat": 2, "name": "BB", "stack": 1000},
                        {"seat": 3, "name": "Hero", "stack": 1000, "cards": ["Js", "Jc"]}],
            "posts": [{"player": "SB", "kind": "sb", "amount": 5}, {"player": "BB", "kind": "bb", "amount": 10}],
            "actions": [{"street": "preflop", "player": "Hero", "kind": "raise", "to": 30},
                        {"street": "preflop", "player": "SB", "kind": "fold"}, {"street": "preflop", "player": "BB", "kind": "call"},
                        {"street": "flop", "player": "BB", "kind": "check"}, {"street": "flop", "player": "Hero", "kind": "bet", "to": 20},
                        {"street": "flop", "player": "BB", "kind": "fold"}],
            "board": ["8h", "6h", "4h"], "hero": "Hero", "notes": notes}


def write_json(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_time_ranges():
    assert knowledge.spans("1:45-5:20") == [(105, 320)]
    assert knowledge.spans("约 11:20–14:50；f_0101，赔率 3.87:1", "11:20–14:50") == [(680, 890)]
    assert knowledge.spans("1:02:03–1:05:00", "5:00–4:00", None) == [(3723, 3900)]


def test_hand_records_are_placed_in_video_time(base, tmp_path):
    write_json(tmp_path / "hands" / "vidAAAAAAA1.json",
               {"video_id": "vidAAAAAAA1", "supersedes": ["draft.json"],
                "hands": [hand_record("hhp-a-h1", "约 0:50–2:10。【画面】Hero J♠J♣。"), hand_record("hhp-a-h0", "没有写时间")],
                "partial": [{"label": "h2 河牌抓诈（2:10–3:00）", "known": {"time": "2:10–3:00"}, "missing": ["尺寸"]}]})
    write_json(tmp_path / "hands" / "draft.json", [hand_record("hhp-a-h1", "旧稿 0:00–9:00")])  # superseded draft
    write_json(tmp_path / "hand_times.json", {"times": {"hhp-a-h0": "0:00–0:40"}})
    kb = knowledge.Knowledge(tmp_path)
    stats = kb.stats()
    assert stats["hand_records"] == 2 and stats["partial_records"] == 1 and "hand_problems" not in stats
    window = kb.read("vidAAAAAAA1", 60, 40)
    [view] = window["hands"]
    assert view["record"] == "hhp-a-h1" and view["time"] == ["0:50–2:10"] and view["url"].endswith("&t=50s")
    assert view["actions"] == "翻前：Hero 加注到 30，SB 弃牌，BB 跟注 30；翻牌：BB 过牌，Hero 下注 20，BB 弃牌"
    assert view["street_end_pots"] == {"翻前": 65, "翻牌": 85} and view["final_pot"] == 65 and view["returned"] == ["Hero", 20]
    assert view["players"][2] == {"name": "Hero", "position": "BTN", "stack": 1000, "cards": ["Js", "Jc"]}
    assert "replay" not in view and "假设" in window["hands_note"]
    assert [h["record"] for h in kb.read("vidAAAAAAA1", 0, 30)["hands"]] == ["hhp-a-h0"]  # time from hand_times.json
    [partial] = kb.read("vidAAAAAAA1", 140, 30)["hands"]
    assert partial["complete"] is False and partial["missing"] == ["尺寸"]
    assert "hands" not in kb.read("vidBBBBBBB2", 0, 60)
    first = next(h for h in kb.search("pocket jacks") if h["start"] == "0:00")
    assert first["hands"] == ["hhp-a-h0", "hhp-a-h1"]
    store = CoachStore(tmp_path / "coach")
    found = tools.execute(store, "read_hhp", {"video_id": "vidAAAAAAA1", "start_seconds": 60, "seconds": 40})
    assert found["hands"][0]["record"] == "hhp-a-h1"


def methods():
    return [{"id": "squeeze-station", "title": "对跟注站少诈唬多价值", "read": "对手翻后几乎不弃牌", "adjustment": "河牌薄价值加注",
             "why": "他跟注的范围太宽", "how_far": None, "limits": "对手突然变紧时停止", "tags": ["type-station", "value-bet"],
             "origin": "hhp", "solver": None, "evidence": [{"video": "abc123xyz00", "time": "1:05", "hand": None, "note": "讲解"},
                                                          {"video": "abc123xyz00", "time": "2:10", "hand": None, "note": "例子"},
                                                          {"video": "abc123xyz00", "time": "bad", "hand": None, "note": "时间不对，不引用"}]},
            {"id": "nit-steal", "title": "紧的盲注多偷", "read": "大盲弃牌过多", "adjustment": "放宽开池", "why": "死钱白拿",
             "tags": ["preflop", "type-nit"], "origin": "blog", "evidence": [{"url": "https://blog.example/a", "title": "文章", "note": "条件不同"}]}]


def test_principles_are_found_in_chinese_and_english(base, tmp_path):
    write_json(tmp_path / "methods" / "methods.json", methods())
    kb = knowledge.Knowledge(tmp_path)
    found = kb.find_methods("跟注站怎么打")
    assert [r["id"] for r in found["results"]] == ["squeeze-station"]
    assert found["results"][0]["evidence_count"] == 2
    assert found["results"][0]["evidence"][1]["url"].endswith("&t=130s")
    assert [r["id"] for r in kb.find_methods("preflop steal", ["type-nit"])["results"]] == ["nit-steal"]
    assert kb.find_methods("跟注站", ["type-nit"])["results"] == []
    assert kb.read_method("nit-steal")["evidence"][0]["url"] == "https://blog.example/a"
    with pytest.raises(ValueError, match="没有这条"):
        kb.read_method("missing")
    assert kb.stats()["methods"] == 2


def test_bad_methods_file_is_reported(base, tmp_path):
    write_json(tmp_path / "methods" / "methods.json", [{"title": "没有编号"}])
    kb = knowledge.Knowledge(tmp_path)
    assert kb.methods == [] and "methods.json" in kb.hand_problems[0]
    (tmp_path / "methods" / "methods.json").write_text("{", encoding="utf-8")
    assert "methods.json" in knowledge.Knowledge(tmp_path).hand_problems[0]


def test_bad_hand_files_are_reported(base, tmp_path):
    write_json(tmp_path / "hands" / "old.json", [])
    bad = hand_record("hhp-a-bad", "0:10–0:20")
    bad["actions"][0]["to"] = None
    write_json(tmp_path / "hands" / "v.json", {"video_id": "vidAAAAAAA1", "hands": [bad, hand_record("hhp-a-h0", "没有写时间")]})
    problems = knowledge.Knowledge(tmp_path).stats()["hand_problems"]
    assert any(p.startswith("old.json") for p in problems)
    assert any("必须给出 to" in p for p in problems)
    assert any("hhp-a-h0 没有视频时间范围" in p for p in problems)


def test_default_reloads_when_hand_files_change(base, tmp_path):
    assert knowledge.default().stats()["hand_records"] == 0
    write_json(tmp_path / "hands" / "vidAAAAAAA1.json", {"video_id": "vidAAAAAAA1", "hands": [hand_record("hhp-a-h1", "0:50–2:10")]})
    assert knowledge.default().stats()["hand_records"] == 1
