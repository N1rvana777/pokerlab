from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START, END = "<!-- shared-mission:start -->", "<!-- shared-mission:end -->"


def shared_block(name: str) -> str:
    text = (ROOT / name).read_text(encoding="utf-8")
    assert text.count(START) == 1 and text.count(END) == 1, name
    return text[text.index(START):text.index(END) + len(END)]


def test_agents_and_claude_share_the_same_mission_block():
    block = shared_block("AGENTS.md")
    assert block == shared_block("CLAUDE.md")
    assert "复盘助手" in block and "验收标准" in block
    assert "Heads-up PLO4" in block and "接近均衡" in block  # paused line, kept in the block
