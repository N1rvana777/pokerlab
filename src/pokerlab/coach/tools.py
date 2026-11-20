"""Coach business tools, shared by every agent provider through ``SolverAgent.execute_tool``.

Confirmation of typed live hands stays a user action in the UI; no tool confirms hands.
"""
from __future__ import annotations

from . import equity, knowledge, situation
from .hands import normalize, replay
from .live import build_live_hand_with_guesses
from .store import NOTE_TOPICS


def _tool(name, description, properties=None, required=None):
    return {"name": name, "description": description, "input_schema": {"type": "object",
            "properties": properties or {}, "required": required or [], "additionalProperties": False}}


METHOD_TAGS = ["preflop","straddle","limp","3bet","4bet","squeeze","multiway","cbet","probe","check-raise","barrel","river-bluff","value-bet","hero-call","bluff-catch","fold","sizing","overbet","deep-stack","short-stack","live-tells","table-dynamic","image","type-nit","type-station","type-maniac","type-reg","type-fish","mindset","bankroll","study-method","game-selection"]
POSITIONS = ["UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN", "SB", "MB", "BB", "EP", "MP", "LP", "blinds"]
CARD = "^[2-9TJQKA][cdhs]$"
EQUITY_BOARDS = 300_000  # preflop boards per call, split over the range's combos
EQUITY_ROWS = 40
LIVE_FORMAT = (
    "现场手牌按位置写，服务器自动排座位、按钮和盲注：hand={hand_id: 形如 live-20261027-jj-vs-villain（字母数字和 ._:-）, "
    "played_at: '2026-10-27', game: {preset 省略=默认级别；bomb pot 加 bomb_pot:true, bomb_pot_ante: 每人底注或省略}, "
    "table_size: 省略=级别默认（9）, players: [{position: SB|MB|BB|UTG|UTG+1|LJ|HJ|CO|BTN（MP 记 LJ）, name: 用户给的名字或标签（自己用 Hero）, "
    "stack: 筹码或 null, cards: ['Jc','Td']，花色未知写 x，如 ['Jx','Jx']，整张不知道写 '??'，如 ['7x','??']}], straddle: {position:'UTG', amount:20}（有 straddle 时）, "
    "actions: 按实际顺序 [{street: preflop|flop|turn|river, player, kind: fold|check|call|bet|raise, to: 本街累计投入（bet/raise 必填）, all_in: 可选}], "
    "board: ['Ax','3x','7x','5h'] 已知花色写出、未知写 x, board_texture: 原文花色信息如 '翻牌两红桃'，showdown: [{player, cards}], "
    "collected: [{player, amount}]（知道才填）, hero: 'Hero', notes: 原文要点和不确定之处}。"
    "没写出的座位自动成为匿名玩家（名字 #UTG+1 这类，可在 actions 里引用）。位置不知道时 position 写 null，系统按行动顺序暂定并返回 position_guesses；"
    "身份不明但有行动的玩家（例如其他 limper）用 #limper2 这类以 # 开头的名字加 position=null 记上，保证底池完整。没提到的行动按弃牌或过牌补记。"
    "盲注不要自己写，除非与默认级别不同。金额是整数美元。未知的牌、筹码和金额写 null，不要编造。")

TOOLS = [
    _tool("import_hand_history", "导入 PokerStars/GG 格式的手牌文本（可多手），代码解析并逐步重放校验；通过校验的手牌自动确认并计入统计，失败的列出原因。",
          {"text": {"type": "string", "minLength": 20, "maxLength": 400000}}, ["text"]),
    _tool("get_review_context", "整理笔记前先调用：默认级别与盲注结构、Hero 名字、所有已知玩家的名字/标签/别名和最近备注。",
          {}),
    _tool("record_live_hand", "提交你从用户笔记整理出的一手现场牌，作为待确认修订保存并返回重放校验结果。用户在“手牌与对手”面板确认后才计入统计；你不能代为确认。" + LIVE_FORMAT,
          {"hand": {"type": "object"}}, ["hand"]),
    _tool("link_player_alias", "把用户对同一个人的不同叫法（如“红帽”“大叔”）指向已有名字（如“红帽大叔”）。只在笔记里明确是同一人时使用，并在回答里说明。",
          {"name": {"type": "string", "minLength": 1, "maxLength": 60}, "target": {"type": "string", "minLength": 1, "maxLength": 60}},
          ["name", "target"]),
    _tool("calc_equity", "算全下到底的胜率：一手牌对一个范围，从翻前、翻牌、转牌或河牌开始。翻前蒙特卡洛，翻后枚举所有发牌。"
          "villain 的写法和 Solver 范围相同，如 'QQ+,AKs,AKo,AQs:0.5,A5s-A2s,AhKh'。牌要写全花色；用户没写花色时挑一个例子，并在回答里写明。"
          "结果里 by_hand 是对每类牌的胜率。不含后面街的下注。",
          {"hero": {"type": "array", "items": {"type": "string", "pattern": CARD}, "minItems": 2, "maxItems": 2},
           "villain": {"type": "string", "minLength": 2, "maxLength": 8000},
           "board": {"type": "array", "items": {"type": "string", "pattern": CARD}, "maxItems": 5}}, ["hero", "villain"]),
    _tool("find_methods", "查方法论条目：看到什么信号、怎么调整、为什么赚钱、偏离多少、什么时候别用。用户问该怎么打、为什么这样剥削、怎么对付某类对手时先查这里。"
          "query 用中文或英文描述处境和对手，tags 可选。结果写明来源（origin）和 Solver 验证情况（solver）；没有验证的只是经验判断。evidence 是视频时间点或文章，完整证据用 read_method。",
          {"query": {"type": "string", "minLength": 2, "maxLength": 200}, "tags": {"type": "array", "items": {"type": "string", "enum": METHOD_TAGS}, "maxItems": 5},
           "limit": {"type": "integer", "minimum": 1, "maximum": 8}}, ["query"]),
    _tool("read_method", "读取一条方法论的全部证据（视频时间点、手牌编号、文章）。",
          {"method_id": {"type": "string", "minLength": 2, "maxLength": 80}}, ["method_id"]),
    _tool("search_hhp", "在 Hungry Horse Poker 视频字幕知识库里检索（用户私人资料）。query 用英文关键词，例如 'limp reraise range jacks'。"
          "返回视频标题、时间点链接、该段原文和命中/缺失的关键词（缺了关键的词说明其实没查到）；这是 HHP 的经验观点，不是 Solver 结论。自动字幕可能听错牌名和金额。"
          "hands 列出这段时间里从视频画面整理出的手牌记录，用 read_hhp 读取。",
          {"query": {"type": "string", "minLength": 2, "maxLength": 200}, "limit": {"type": "integer", "minimum": 1, "maximum": 8}}, ["query"]),
    _tool("read_hhp", "读取某个 HHP 视频从某个时间点开始的一段字幕原文（默认 120 秒），用于核对 search_hhp 找到的内容。"
          "这段时间如果有从画面整理、通过重放校验的手牌记录，也一起返回（底牌、公共牌、每步行动和尺寸、各街底池、来源备注）。",
          {"video_id": {"type": "string", "minLength": 5, "maxLength": 20}, "start_seconds": {"type": "integer", "minimum": 0},
           "seconds": {"type": "integer", "minimum": 10, "maximum": 600}}, ["video_id", "start_seconds"]),
    _tool("find_hhp_hands", "按牌局处境查 HHP 视频手牌记录：底牌、位置、筹码深度、底池类型、牌面、Hero 每街的行动和面对的下注。比逐段读字幕快，也能找到讲解人没有说出牌名的手牌。"
          "复盘用户已记录的手牌时传 similar_to，自动取这手牌的处境找最接近的视频手牌。条件都可选，可以组合。"
          "结果按符合的条件多少排序，matched / missed 写明符合和不符合的条件；missed 不为空的只是相近，不是同一处境。exact_total 是完全符合的总数，exact_by_video 是分布，每个视频最多返回 3 手，可用 video_id 看全。"
          "返回行动线、结果底池、讲解人思路的开头、视频时间和链接；完整记录和字幕用 read_hhp 读那段时间。这是 HHP 的经验观点，不是 Solver 结论。",
          {"similar_to": {"type": "string", "minLength": 1, "maxLength": 80, "description": "用户手牌编号"},
           "cards": {"type": "array", "items": {"type": "string", "maxLength": 4}, "maxItems": 20,
                     "description": "Hero 的牌型，任一符合：JJ、AKs、AKo、AK（不分同花）、Ax（任意 A）、Axs（任意同花 A）"},
           "position": {"type": "array", "items": {"type": "string", "enum": POSITIONS}, "description": "Hero 的位置，任一符合；EP/MP/LP/blinds 是分组"},
           "opponent_position": {"type": "array", "items": {"type": "string", "enum": POSITIONS}, "description": "同 Hero 争底池的对手位置，任一符合"},
           "depth_min_bb": {"type": "number", "minimum": 0, "description": "有效筹码下限，单位大盲；有 straddle 时按 straddle 算"},
           "depth_max_bb": {"type": "number", "minimum": 0, "description": "有效筹码上限，单位同上"},
           "pot_type": {"type": "array", "items": {"type": "string", "enum": list(situation.POT_TYPES)},
                        "description": "翻前底池类型，任一符合；iso 是 limp 后的隔离加注，squeeze 是有人跟注后的 3bet"},
           "in_position": {"type": "boolean", "description": "Hero 翻后最后行动"},
           "multiway": {"type": "boolean", "description": "三人及以上看翻牌"},
           "board": {"type": "array", "items": {"type": "string", "enum": list(situation.BOARD_TAGS)},
                     "description": "翻牌特征，全部符合；low 是 9 及以下最大，connected 是三张牌能成顺，dry 是彩虹不连，wet 是同花听牌加连张"},
           "line": {"type": "array", "items": {"type": "string", "maxLength": 30},
                    "description": "Hero 的行动，全部符合，格式 街:动作。翻前：open、iso、3bet、squeeze、4bet、5bet、limp、call、call_open、call_3bet、call_4bet、fold、fold_open、fold_3bet、fold_4bet。翻后（flop/turn/river）：check、bet、call、raise、fold、cbet（上一街的进攻方继续下注）、donk（抢在上一街进攻方之前下注），以及连写的 check_raise、check_call、check_fold、bet_fold、bet_call、bet_raise"},
           "facing": {"type": "array", "items": {"type": "string", "maxLength": 30},
                      "description": "Hero 面对的动作，全部符合，格式 街:动作。翻前：open、iso、3bet、squeeze、4bet、5bet、all_in。翻后：bet、raise、reraise、check_raise、all_in"},
           "text": {"type": "string", "maxLength": 100, "description": "备注里的关键词，空格分开，全部符合；备注多为中文，如 阻断、抽水"},
           "video_id": {"type": "string", "minLength": 5, "maxLength": 20, "description": "只看这个视频"},
           "limit": {"type": "integer", "minimum": 1, "maximum": 20}}),
    _tool("list_hands", "列出手牌及状态（confirmed 已计入统计 / pending 待确认 / has_errors 有错误 / new_revision 有新修订待确认）。",
          {"player": {"type": "string", "maxLength": 60}, "status": {"type": "string", "enum": ["all", "confirmed", "pending"]},
           "limit": {"type": "integer", "minimum": 1, "maximum": 200}}),
    _tool("get_hand", "读取一手牌：统一格式、重放结果（位置、底池、错误与警告）、产生的统计观察和已知底牌。",
          {"hand_id": {"type": "string", "minLength": 1, "maxLength": 80}, "revision": {"type": "integer", "minimum": 1}}, ["hand_id"]),
    _tool("list_players", "列出已确认手牌中的玩家：手数、原始 VPIP/PFR、暂定类型和最可信的标签。",
          {"include_hero": {"type": "boolean"}}),
    _tool("get_player_profile", "读取一名玩家的完整档案：每项统计的机会定义、样本数、原始比例、后验均值、90% 区间、倾向分、证据手牌，以及标签、类型、摊牌记录和备注。先验是否校准也在结果里。",
          {"player": {"type": "string", "minLength": 1, "maxLength": 60}}, ["player"]),
    _tool("add_player_note", "给玩家写一条备注。kind=observation：用户自己的场外描述（心情、动作、tell、形象、他对对手 VPIP 的判断等），尽量保留原话，可以不引用手牌；"
          "kind=inference：你的推断，必须引用支持它的手牌编号。topic 选 mood / tell / image / read / tendency / other；session 写日期如 2026-10-27。",
          {"player": {"type": "string", "minLength": 1, "maxLength": 60}, "text": {"type": "string", "minLength": 1, "maxLength": 2000},
           "kind": {"type": "string", "enum": ["observation", "inference"]}, "topic": {"type": "string", "enum": list(NOTE_TOPICS)},
           "session": {"type": "string", "maxLength": 20},
           "hand_ids": {"type": "array", "items": {"type": "string", "maxLength": 80}, "maxItems": 20}},
          ["player", "text", "kind"]),
]
NAMES = {t["name"] for t in TOOLS}


def execute(store, name, args):
    if name == "import_hand_history":
        results = store.import_text(args["text"])
        return {"results": results, "imported": sum(r["result"] == "stored" for r in results),
                "duplicates": sum(r["result"] == "duplicate" for r in results),
                "rejected": sum(r["result"] == "rejected" for r in results)}
    if name == "calc_equity":
        board = args.get("board", [])
        if len(board) not in (0, 3, 4, 5):
            raise ValueError("公共牌只能是 0、3、4 或 5 张")
        villain = equity.parse_range(args["villain"])
        combos = sum(len(equity.expand(token)) for token, _ in villain)
        result = equity.equity(args["hero"], villain, boards=max(500, min(10_000, EQUITY_BOARDS // combos)), board=board)
        rows = sorted(result["by_hand"], key=lambda row: -row["combos"] * row["weight"])
        return {**result, "by_hand": rows[:EQUITY_ROWS], "by_hand_total": len(rows), "note": "全下到底的胜率，范围是输入的假设。"}
    if name == "find_methods":
        return {**knowledge.default().find_methods(args["query"], args.get("tags"), args.get("limit", 5)),
                "note": "讲解人和文章作者的方法，不是 Solver 结论，也不是用户对手的证据。solver 为空表示没有验证过。"}
    if name == "read_method":
        return knowledge.default().read_method(args["method_id"])
    if name == "search_hhp":
        base = knowledge.default()
        return {"results": base.search(args["query"], args.get("limit", 5)), "knowledge_base": base.stats(),
                "note": "HHP 视频观点（自动字幕），引用时写标题和时间点；不是 Solver 结论，也不是对手统计。"
                        "结果里的 hands 是这段时间有画面整理的手牌记录，用 read_hhp 读取。"}
    if name == "read_hhp":
        return knowledge.default().read(args["video_id"], args["start_seconds"], args.get("seconds", 120))
    if name == "find_hhp_hands":
        criteria = {key: value for key, value in args.items() if key not in ("similar_to", "limit")}
        if args.get("similar_to"):
            hand = store.record(args["similar_to"])["hand"]
            found = situation.features(hand, replay(hand))
            if found is None:
                raise ValueError("这手牌没有标明 Hero，无法判断处境；请直接给条件")
            criteria = {**situation.criteria_of(found), **criteria}
        return {**knowledge.default().find(criteria, args.get("limit", 6)), "criteria": criteria,
                "note": "HHP 视频手牌（教学场景或别人的牌局），不是 Solver 结论，也不是用户对手的证据。missed 不为空的只是相近。"
                        "引用时写记录编号和时间点，完整记录和字幕用 read_hhp 读。"}
    if name == "get_review_context":
        return store.context()
    if name == "link_player_alias":
        return store.link_alias(args["name"], args["target"])
    if name == "record_live_hand":
        # A note that lacks an amount is an expected outcome, not a failed tool. Revisions cannot be deleted, so nothing is kept.
        try:
            hand, guesses = build_live_hand_with_guesses(args["hand"], store.default_game())
            problems = replay(normalize(hand)).errors
        except ValueError as exc:
            hand, guesses, problems = None, None, [str(exc)]
        if problems:
            return {"result": "not_stored", "errors": problems, "position_guesses": guesses,
                    "next_step": "这一手没有保存。能修正就重新提交；缺关键金额时不要删掉行动来绕过校验，把缺什么告诉用户。"}
        status = store.add_hand(hand, "agent")
        detail = store.hand_detail(status["hand_id"], status["latest_revision"])
        return {**status, "replay": detail["replay"], "position_guesses": guesses,
                "next_step": "请用户在“手牌与对手”面板核对并确认；有错误时修正后重新提交。位置是暂定的要告诉用户。"}
    if name == "list_hands":
        return {"hands": store.list_hands(args.get("status", "all"), args.get("player"), args.get("limit", 50))}
    if name == "get_hand":
        return store.hand_detail(args["hand_id"], args.get("revision"))
    if name == "list_players":
        return {"players": store.players(args.get("include_hero", True)), "hero_names": store.hero_names()}
    if name == "get_player_profile":
        return store.player_profile(args["player"])
    if name == "add_player_note":
        return store.add_note(args["player"], args["text"], args.get("hand_ids", []), "agent", args["kind"],
                              args.get("topic"), args.get("session"))
    raise ValueError("未知复盘工具：" + name)
