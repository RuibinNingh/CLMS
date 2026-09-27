"""端到端主路径（真浏览器）：自建临时数据目录 + 假模型 + 随机端口，跑完即清理。

    python3 tests/e2e_main.py              # 断言主路径
    python3 tests/e2e_main.py --shots DIR  # 另存关键截图（桌面、深色、手机）

覆盖：空状态 → 一次选三张图（每张一份）→ 后台排队识别（Agent：主代理委派子代理，执行记录里有子代理卡片）
→ 对话修订（改动清单、画布闪一次、回到修改前）→ 手工改留白 → 入库 → 第二份含标点不同的重复默写（去重、记又错一次）
→ 题库（复习记录补记 / 改评 / 撤销 / 恢复，删除后恢复）→ 按时间预算排复习 → 评分 → 写反馈 → 拍照交给 AI 批改
→ 新对话里让 AI 停用一道题 → 打印 → 概览 → 设置里导出脱敏源码。
需要 playwright（自带 Chromium）。测试图片用 Pillow 现画，不依赖外部文件。
"""

import argparse
import os
import shutil
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fake_ai  # noqa: E402
from clms.common import save_config  # noqa: E402
from clms.server import make_server  # noqa: E402


def make_images(folder):
    from PIL import Image, ImageDraw
    paths = []
    for index, tint in enumerate(((250, 249, 244), (246, 248, 250), (250, 246, 240))):
        img = Image.new("RGB", (900, 1200), tint)
        draw = ImageDraw.Draw(img)
        for row in range(40, 1160, 36):
            draw.line((60, row, 840 - (row * 7 % 200), row), fill=(60, 60, 60), width=3)
        path = os.path.join(folder, f"exam-{index}.jpg")
        img.save(path, quality=80)
        paths.append(path)
    return paths


def run(shots=None):
    from playwright.sync_api import sync_playwright
    vault = tempfile.mkdtemp(prefix="clms-e2e-")
    ai = fake_ai.start(0)
    save_config(vault, {"ai_base_url": f"http://127.0.0.1:{ai.server_address[1]}/v1", "ai_api_key": "k", "ai_model": "fake"})
    server = make_server(vault, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    images = make_images(vault)
    errors = []

    def shot(page, name, **kw):
        if shots:
            page.screenshot(path=os.path.join(shots, name), **kw)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            pg.on("console", lambda m: m.type in ("error", "warning") and errors.append(f"{m.type}: {m.text}"))

            pg.goto(base + "/#/entry")
            pg.wait_for_selector(".drop")
            shot(pg, "01-empty.png")
            pg.set_input_files('input[data-change="entry.files"]', images)
            pg.wait_for_selector(".pending")
            pg.click('[data-action="entry.upload"][data-arg="split"]')
            pg.wait_for_function("document.querySelectorAll('.qchip[data-tone=\"ready\"]').length === 3", timeout=30000)
            pg.click('.qchip:has-text("老街的灯")')
            pg.wait_for_selector('.grp[data-genre="modern"]')
            pg.click(".run__head >> nth=0")
            pg.wait_for_selector(".run__task")
            tasks = pg.eval_on_selector_all(".run__task", "els => els.map(e => e.dataset.status)")
            assert tasks == ["done", "done"], tasks
            shot(pg, "02-workbench.png")
            pg.click(".run__head >> nth=0")

            pg.fill("#composer", "第7题答案按采分点重写，留白 9 行")
            pg.keyboard.press("Enter")
            pg.wait_for_selector(".msg__changes", timeout=15000)
            assert pg.input_value("#composer") == ""
            labels = pg.eval_on_selector_all(".msg__changes .chip", "els => els.map(e => e.textContent.trim())")
            assert labels == ["第 7 题 · 答案", "第 7 题 · 留白"], labels
            pg.wait_for_selector("[data-flash]")
            shot(pg, "03-revised.png")
            assert "留白 9 行" in pg.inner_text('[data-anchor="g1|i2"]')
            pg.click('.msg__changes [data-action="entry.restore"]')
            pg.wait_for_function("document.querySelector('[data-anchor=\"g1|i2\"]').innerText.includes('留白 7 行')")

            pg.click('[data-anchor="g1|i2"] [data-action="entry.lines"][data-arg="1"]')
            pg.wait_for_function("document.querySelector('.sheet__rev').innerText.includes('已保存')")
            assert "留白 8 行" in pg.inner_text('[data-anchor="g1|i2"]')
            assert pg.inner_text(".sheet__check").startswith("入库后新增 6 题"), pg.inner_text(".sheet__check")
            pg.click('[data-action="entry.commit"]')
            pg.wait_for_selector(".sheet__foot.is-done")

            pg.click('.qchip:has-text("山居秋暝")')
            pg.wait_for_selector('.grp[data-genre="poetry"]')
            check = pg.inner_text(".sheet__check")
            assert "新增 2 题" in check and "1 题库里已有" in check, check
            assert pg.locator('.dict .chip--warn:has-text("库中已有")').count() == 1
            pg.click('[data-action="entry.commit"]')
            pg.wait_for_selector(".sheet__foot.is-done")
            assert "1 题库里已有、记为又错一次" in pg.inner_text(".sheet__foot")

            pg.goto(base + "/#/library")
            pg.wait_for_selector(".row")
            assert pg.locator(".row").count() == 8, pg.locator(".row").count()
            pg.click('.row:has-text("静夜思")')
            pg.wait_for_selector(".lib__detail")
            assert "2 次录入" in pg.inner_text(".lib__stats")
            pg.select_option('.rec__add select[name="grade"]', "1")
            pg.click('.rec__add button')
            pg.wait_for_selector(".rec")
            pg.select_option(".rec__grade", "3")
            pg.wait_for_function("document.querySelectorAll('.rec').length === 1 && document.querySelector('.rec__grade').value === '3'")
            pg.click('.rec [data-action="lib.void"]')
            pg.wait_for_selector('[data-action="lib.showVoided"]')
            pg.click('[data-action="lib.showVoided"]')
            pg.wait_for_selector(".rec.is-void")
            pg.click('.rec.is-void [data-action="lib.unvoid"] >> nth=0')
            pg.wait_for_function("document.querySelectorAll('.rec:not(.is-void)').length === 1")
            shot(pg, "04-library.png")
            pg.click('.row:has-text("山居秋暝") >> nth=0')
            pg.wait_for_selector('.lib__detail[data-genre="poetry"]')
            pg.click('[data-action="lib.delete"]')
            pg.click('dialog.dlg button[value="yes"]')
            pg.wait_for_function("document.querySelectorAll('.row').length === 7")
            pg.select_option('select[data-arg="status"]', "deleted")
            pg.wait_for_function("document.querySelectorAll('.row').length === 1")
            pg.click(".row")
            pg.click('[data-action="lib.restore"]')
            pg.wait_for_selector('[data-action="lib.delete"]')
            pg.select_option('select[data-arg="status"]', "")
            pg.wait_for_function("document.querySelectorAll('.row').length === 8")

            pg.goto(base + "/#/review")
            pg.click('[data-action="rv.budget"][data-arg="60"]')
            pg.click('[data-action="rv.plan"]')
            pg.wait_for_selector(".rv__pick li")
            pg.click('[data-action="rv.create"]')
            pg.wait_for_selector(".rv__grading")
            pg.click(".rv__reveal >> nth=0")
            pg.click('.rv__grades >> nth=0 >> [data-grade="2"]')
            pg.wait_for_selector('.gbtn[aria-pressed="true"][data-grade="2"]')
            pg.click('[data-action="rv.noteEdit"] >> nth=0')
            pg.fill(".rv__noteinput", "漏了第二个采分点")
            pg.keyboard.press("Enter")
            pg.wait_for_selector('.rv__note:has-text("漏了第二个采分点")')
            shot(pg, "05-grading.png")
            href = pg.get_attribute(".rv__ghead a", "href")
            pr = ctx.new_page()
            pr.goto(base + href + "&answers=1")
            assert pr.locator(".lines div").count() > 20 and pr.locator(".blank").count() >= 2
            shot(pr, "06-print.png", full_page=True)
            pg.set_input_files('input[data-change="rv.aiGrade"]', images[:1])
            pg.wait_for_selector('.qchip.is-active:has-text("批改")', timeout=15000)
            pg.wait_for_function("document.querySelector('.run[data-state=\"done\"]')", timeout=30000)
            assert "review_grade" not in pg.inner_text(".chat__log")
            pg.click(".run__head >> nth=0")
            assert "批改" in pg.inner_text(".run__steps")
            shot(pg, "06b-ai-grading.png")
            pg.goto(base + "/#/review")
            pg.wait_for_selector(".rv__row")
            assert "已评完" in pg.inner_text(".rv__row >> nth=0")

            pg.goto(base + "/#/entry")
            pg.click('[data-action="entry.newChat"]')
            pg.wait_for_selector(".msg--note:has-text('空白对话')")
            pg.fill("#composer", "停用 Q-000003")
            pg.keyboard.press("Enter")
            pg.wait_for_function("document.querySelector('.run[data-state=\"done\"]')", timeout=30000)
            assert "Q-000003 已停用" in pg.inner_text(".chat__log")

            pg.goto(base + "/#/dashboard")
            pg.wait_for_selector(".hero")
            assert pg.locator(".day.is-review").count() >= 4
            pg.click('[data-action="app.theme"]')
            shot(pg, "07-dashboard-dark.png", full_page=True)
            pg.click('[data-action="app.theme"]')

            pg.goto(base + "/#/settings")
            pg.wait_for_selector('[data-testid="source-export"]')
            assert pg.is_checked('input[name="ai_agent"]')
            with pg.expect_download() as info:
                pg.click('[data-testid="source-export"]')
            assert info.value.suggested_filename.startswith("CLMS-source-sanitized-"), info.value.suggested_filename
            shot(pg, "10-settings.png", full_page=True)

            mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            mp = mobile.new_page()
            mp.on("pageerror", lambda e: errors.append(f"mobile pageerror: {e}"))
            mp.goto(base + "/#/entry")
            mp.wait_for_selector(".qchip")
            mp.click('.qchip:has-text("咏雪")')
            mp.wait_for_selector(".canvas")
            assert mp.evaluate("document.documentElement.scrollWidth") <= 390
            shot(mp, "08-mobile-draft.png")
            mp.click('[data-action="entry.tab"][data-arg="chat"]')
            shot(mp, "09-mobile-chat.png")
            browser.close()
        assert not errors, errors
        print("e2e 主路径通过")
    finally:
        server.shutdown()
        server.server_close()
        ai.shutdown()
        ai.server_close()
        shutil.rmtree(vault, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shots", default=None)
    args = parser.parse_args()
    if args.shots:
        os.makedirs(args.shots, exist_ok=True)
    run(args.shots)
