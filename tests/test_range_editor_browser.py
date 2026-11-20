"""169-class range interaction and independent 1326-combo numeric acceptance.

No solver jobs are launched and existing 8765/8770 services are untouched.
"""
import json
from pathlib import Path
import shutil
import socket
import subprocess
import threading

import pytest

from pokerlab.solver.server import make_server

ROOT = Path(__file__).resolve().parents[1]
RANGE_JS = ROOT / "src/pokerlab/solver/web/range.js"


def test_percent_template_preserves_1326_mass_and_uniform_classes():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable for JavaScript range numeric checks")
    script = RANGE_JS.read_text(encoding="utf-8") + """
    const cases = [0, .1, 3, 12.5, 70, 99.9, 100].map(percent => {
      const weights=RangeEditor.fromPercent(percent), classes=RangeEditor.ranking();
      const groups=classes.map(item=>{const values=RangeEditor.combosFor(item.name).map(c=>weights.get(c)||0);return {name:item.name,count:values.length,uniform:values.every(v=>v===values[0]),weight:values[0]}});
      const round=RangeEditor.parse(RangeEditor.serialize(weights));
      return {percent,mass:[...weights.values()].reduce((a,b)=>a+b,0),groups,round:[...weights].every(([c,w])=>round.get(c)===w)};
    });
    console.log(JSON.stringify({cases,rank:RangeEditor.ranking(),invalid:[-1,101,NaN,true].map(p=>{try{RangeEditor.fromPercent(p);return false}catch{return true}})}));
    """
    run = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    rank = result["rank"]
    assert len(rank) == len({x["name"] for x in rank}) == 169
    assert sum(x["count"] for x in rank) == 1326
    assert rank[0]["name"] == "AA"
    assert next(x for x in rank if x["name"] == "AKs")["score"] > next(x for x in rank if x["name"] == "AKo")["score"]
    assert result["invalid"] == [True]*4
    for item in result["cases"]:
        assert item["mass"] == pytest.approx(1326*item["percent"]/100, abs=1e-8)
        assert item["round"]
        assert all(group["uniform"] for group in item["groups"])
        assert all(group["count"] == (6 if len(group["name"]) == 2 else 4 if group["name"].endswith("s") else 12) for group in item["groups"])
        assert sum(0 < group["weight"] < 1 for group in item["groups"]) <= 1
        # A prefix selection has full classes, optionally one fractional class,
        # then zeros. This check is independent of the heuristic score formula.
        weights = [group["weight"] for group in item["groups"]]
        assert weights == sorted(weights, reverse=True)


def test_real_range_click_wheel_drag_percentage_and_undo(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    assert port not in (8765, 8770)
    server = make_server(port, agent_dir=tmp_path / 'agent')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}")
            playwright.expect(page.locator("#board")).to_have_value("9h 8h 2c")
            oop, ip = page.locator("#range-editor0"), page.locator("#range-editor1")
            playwright.expect(oop.locator(".cell")).to_have_count(169)
            playwright.expect(ip.locator(".cell")).to_have_count(169)
            original_ip = page.locator("#range1").input_value()
            text = page.locator("#range0")
            aa = oop.locator('[data-hand="AA"]')
            text.fill("")
            aa.click()
            playwright.expect(aa).to_have_attribute("data-weight", "1")
            aa.click()
            playwright.expect(aa).to_have_attribute("data-weight", "0")
            aa.press("Enter")
            playwright.expect(aa).to_have_attribute("data-weight", "1")
            aa.press("Enter")
            playwright.expect(aa).to_have_attribute("data-weight", "0")
            box = aa.bounding_box()
            page.mouse.move(box["x"]+box["width"]/2, box["y"]+box["height"]/2)
            page.mouse.wheel(0, -100)
            playwright.expect(aa).to_have_attribute("data-weight", "0.05")
            page.keyboard.down("Shift")
            page.mouse.wheel(0, -100)
            page.keyboard.up("Shift")
            playwright.expect(aa).to_have_attribute("data-weight", "0.06")
            page.mouse.wheel(0, 100)
            playwright.expect(aa).to_have_attribute("data-weight", "0.01")
            page.mouse.wheel(0, 100)
            playwright.expect(aa).to_have_attribute("data-weight", "0")
            text.fill("AA:0.99")
            page.mouse.wheel(0, -100)
            playwright.expect(aa).to_have_attribute("data-weight", "1")
            page.mouse.wheel(0, -100)
            playwright.expect(aa).to_have_attribute("data-weight", "1")
            # Drag applies the toolbar's weight rather than toggling each cell.
            text.fill("")
            oop.get_by_label("范围权重百分比", exact=True).fill("50")
            first = oop.locator('[data-hand="KK"]').bounding_box()
            last = oop.locator('[data-hand="KQs"]').bounding_box()
            page.mouse.move(first["x"]+first["width"]/2, first["y"]+first["height"]/2)
            page.mouse.down()
            page.mouse.move(last["x"]+last["width"]/2, last["y"]+last["height"]/2, steps=5)
            page.mouse.up()
            playwright.expect(oop.locator('[data-hand="KK"]')).to_have_attribute("data-weight", "0.5")
            playwright.expect(oop.locator('[data-hand="KQs"]')).to_have_attribute("data-weight", "0.5")
            painted = text.input_value()
            page.locator("#undo").click()
            playwright.expect(text).to_have_value("")
            page.locator("#redo").click()
            playwright.expect(text).to_have_value(painted)
            # Advanced asymmetric input remains exact; a board conflict changes
            # effective counts, never the original weights or input text.
            text.fill("AsAh:0.25,AA:0.5,AKs")
            oop.get_by_label("范围编辑模式").select_option("inspect")
            aa.click()
            exact = oop.locator('[data-combo="AcAd"]')
            exact.fill("25")
            exact.press("Tab")
            playwright.expect(oop).to_contain_text("加权 6.50")
            asymmetric = text.input_value()
            page.locator("#board").fill("Ac 8h 2c")
            playwright.expect(oop).to_contain_text("有效 6 组合 · 加权 4.25 · 公共牌冲突 4")
            assert text.input_value() == asymmetric
            before = page.evaluate("Object.fromEntries(RangeEditor.parse(document.querySelector('#range0').value))")
            oop.get_by_label("范围编辑模式").select_option("paint")
            assert oop.locator(".suit-editor").is_hidden()
            kk = oop.locator('[data-hand="KK"]')
            kk.scroll_into_view_if_needed()
            box = kk.bounding_box()
            page.mouse.move(box["x"]+box["width"]/2, box["y"]+box["height"]/2)
            page.mouse.wheel(0, -100)
            playwright.expect(kk).to_have_attribute("data-weight", "0.05")
            after = page.evaluate("Object.fromEntries(RangeEditor.parse(document.querySelector('#range0').value))")
            assert all(after[combo] == weight for combo, weight in before.items())
            # 70% means 928.2 weighted ORIGINAL combinations. Changing the board
            # does not alter this percentage or the same-suit class weights.
            prior = text.input_value()
            total = page.locator("#range-total-number0")
            total.fill("70")
            total.press("Tab")
            playwright.expect(oop.locator("output")).to_contain_text("70.00% · 928.20 / 1326")
            values = page.evaluate("() => {const w=RangeEditor.parse(document.querySelector('#range0').value);return {mass:[...w.values()].reduce((s,v)=>s+v,0),groups:[...document.querySelectorAll('#range-editor0 .cell')].map(c=>RangeEditor.combosFor(c.dataset.hand).map(k=>w.get(k)||0))}}")
            assert values["mass"] == pytest.approx(928.2, abs=1e-8)
            assert all(group == [group[0]]*len(group) for group in values["groups"])
            seventy = text.input_value()
            page.locator("#undo").click()
            playwright.expect(text).to_have_value(prior)
            page.locator("#redo").click()
            playwright.expect(text).to_have_value(seventy)
            page.locator("#board").fill("9h 8h 2c")
            assert text.input_value() == seventy
            playwright.expect(total).to_have_value("70")
            slider = page.locator("#range-total0")
            slider.fill("0")
            playwright.expect(text).to_have_value("")
            slider.fill("100")
            playwright.expect(oop.locator("output")).to_contain_text("1326.00 / 1326")
            assert page.locator("#range1").input_value() == original_ip
            text.fill("broken-range")
            playwright.expect(aa).to_be_disabled()
            playwright.expect(slider).to_be_disabled()
            playwright.expect(total).to_be_disabled()
            browser.close()
        assert errors == []
    finally:
        server.shutdown()
        server.server_close()
        server.jobs.close()
        thread.join(timeout=5)
