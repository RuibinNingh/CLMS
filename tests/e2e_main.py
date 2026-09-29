"""端到端主路径（真浏览器）：自建临时数据目录 + 假模型 + 随机端口，跑完即清理。

    python3 tests/e2e_main.py              # 断言主路径
    python3 tests/e2e_main.py --shots DIR  # 另存关键截图（桌面、深色、手机）

覆盖：空状态 → 一次选三张图 → 准备阶段（调页序：箭头 + 拖动、旋转、每页说明）→ 每页一份分别识别
→ 时间线（思考块、工具调用展开参数 / 结果、delegate 子代理卡片展开子代理自己的时间线）
→ 对话修订（流式：思考 / 参数逐字出现；改动清单、画布闪一次、回到修改前）→ 录入记录（重命名、回收站、恢复）→ 手工改留白 → 入库 → 第二份含标点不同的重复默写（去重、记又错一次）
→ 题库（复习记录补记 / 改评 / 撤销 / 恢复，删除后恢复；分面筛选；按篇；批量加入复习）
→ 复习页（自选题 + 推荐、移除 / 放回、从题库挑题、按时间预算）→ 评分（一次一道、答题卡、键盘换题 / 自评）→ 写反馈 → 打印
→ 复习助手（思考与查阅可见、选中题干引用、打分并采用、写反馈先暂存评分时写入、改评分保留反馈）→ 复习记录分页
→ 新对话里让 AI 停用一道题 → 概览 → 设置里导出脱敏源码。
需要 playwright（自带 Chromium）。测试图片用 Pillow 现画，不依赖外部文件。
"""

import argparse
import json
import os
os.environ.setdefault("FAKE_AI_STREAM_DELAY", "0.02")   # 让流式看得见
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
            ctx = browser.new_context(viewport={"width": 1600, "height": 900})
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            pg.on("console", lambda m: m.type in ("error", "warning") and errors.append(f"{m.type}: {m.text}"))
            pg.on("response", lambda r: r.status >= 400 and errors.append(f"HTTP {r.status} {r.request.method} {r.url}"))

            pg.goto(base + "/#/entry")
            pg.wait_for_selector(".launch")
            shot(pg, "01-empty.png")
            pg.fill("#composer", "只录阅读和默写")                       # 先写话、再传图：话留着当补充说明
            pg.set_input_files('.launch input[data-change="entry.files"]', images)
            pg.wait_for_selector(".launch__pages")
            pg.wait_for_function("document.querySelectorAll('.launch__pages .page[data-page]').length === 3")  # 上传中先画占位卡
            assert pg.input_value("#composer") == "只录阅读和默写"
            order = lambda: pg.eval_on_selector_all(".page[data-page] img", "els => els.map(e => e.getAttribute('src'))")  # noqa: E731
            before = order()
            pg.click('[data-action="entry.pageMove"][data-arg="2:-1"]')
            pg.wait_for_function("arr => document.querySelectorAll('.page[data-page] img')[1].getAttribute('src') === arr[2]", arg=before)
            moved = order()
            pg.drag_and_drop('.page[data-page="0"]', '.page[data-page="1"]')
            pg.wait_for_function("arr => document.querySelectorAll('.page[data-page] img')[0].getAttribute('src') === arr[1]", arg=moved)
            pg.click('[data-action="entry.pageRotate"][data-arg="0"]')
            pg.wait_for_selector('.page[data-page="0"] .page__img[data-rotate="90"]')
            pg.fill('.page[data-page="1"] .page__note', "题目页")
            pg.press('.page[data-page="1"] .page__note', "Tab")
            pg.wait_for_function("document.querySelector('.hrow.is-active') !== null")
            shot(pg, "01b-stage.png")
            pg.click('[data-action="entry.split"][data-arg="each"]')
            pg.click('[data-action="entry.start"][data-arg="split"]')
            pg.wait_for_selector(".chat .composer__box", timeout=15000)           # 输入框落到对话底部
            pg.wait_for_selector('.tl__item[data-role="user"].is-enter')
            pg.wait_for_function("document.querySelectorAll('.hrow[data-tone=\"ready\"]').length === 3", timeout=60000)
            pg.click('.hrow:has-text("老街的灯") .hrow__main')
            pg.wait_for_selector('.grp[data-genre="modern"]')
            assert pg.locator(".tl .blk--thinking").count() >= 2
            assert pg.locator('.blk--tool[data-tool="delegate"] .task[data-status="done"]').count() == 2
            pg.click('.blk--tool[data-tool="delegate"] .task__head >> nth=0')
            pg.wait_for_selector(".task__log .blk--tool")
            pg.click('.blk--tool[data-tool="delegate"] > .blk__head')
            assert '"tasks"' in pg.inner_text('.blk--tool[data-tool="delegate"] .blk__pre >> nth=0')
            shot(pg, "02-workbench.png")

            os.environ["FAKE_AI_STREAM_DELAY"] = "0.12"          # 这一步放慢流式，保证能看到「进行中」的中间态（机器忙时事件会成批到达）
            pg.fill("#composer", "第7题答案按采分点重写，留白 9 行")
            pg.keyboard.press("Enter")
            pg.wait_for_selector('.blk--thinking[data-status="streaming"], .blk--tool[data-status="preparing"], .blk--text.is-live', timeout=20000)
            shot(pg, "02b-streaming.png")
            os.environ["FAKE_AI_STREAM_DELAY"] = "0.02"
            pg.wait_for_selector(".blk--run .msg__changes", timeout=40000)
            assert pg.input_value("#composer") == ""
            want = ["第 7 题 · 答案", "第 7 题 · 留白"]
            pg.wait_for_function("want => JSON.stringify([...document.querySelectorAll('.blk--run .msg__changes .chip')]"
                                 ".map(e => e.textContent.trim())) === JSON.stringify(want)", arg=want, timeout=10000)
            pg.hover(".gauge")
            pg.wait_for_function("getComputedStyle(document.querySelector('.gauge__pop')).opacity === '1'")
            pop = pg.inner_text(".gauge__pop")
            assert "上下文" in pop and "tok/s" in pop and "主代理" in pop, pop
            shot(pg, "02c-gauge.png")
            pg.mouse.move(5, 5)
            pg.wait_for_selector("[data-flash]")
            shot(pg, "03-revised.png")
            assert "留白 9 行" in pg.inner_text('[data-anchor="g1|i2"]')
            pg.click('.blk--run .msg__changes [data-action="entry.restore"]')
            pg.wait_for_function("document.querySelector('[data-anchor=\"g1|i2\"]').innerText.includes('留白 7 行')")

            pg.click('[data-anchor="g1|i2"] [data-action="entry.lines"][data-arg="1"]')
            pg.wait_for_function("document.querySelector('.sheet__rev').innerText.includes('已保存')")
            assert "留白 8 行" in pg.inner_text('[data-anchor="g1|i2"]')
            assert pg.inner_text(".sheet__check").startswith("入库后新增 6 题"), pg.inner_text(".sheet__check")
            pg.click('[data-action="entry.commit"]')
            pg.wait_for_selector(".sheet__foot.is-done")

            pg.click('.hrow:has-text("山居秋暝") .hrow__main')
            pg.wait_for_selector('.grp[data-genre="poetry"]')
            check = pg.inner_text(".sheet__check")
            assert "新增 2 题" in check and "1 题库里已有" in check, check
            assert pg.locator('.dict .chip--warn:has-text("库中已有")').count() == 1
            pg.click('[data-action="entry.commit"]')
            pg.wait_for_selector(".sheet__foot.is-done")
            assert "1 题库里已有、记为又错一次" in pg.inner_text(".sheet__foot")
            pg.click('.sheet__foot [data-action="entry.fresh"]')                # 入库后「录下一份」回到居中输入框
            pg.wait_for_selector(".launch .launch__title")
            pg.click('[data-action="entry.collapse"]')
            pg.wait_for_selector('.entry[data-collapsed="true"] .hist[inert]')
            pg.click('[data-action="app.nav"]')
            pg.wait_for_selector('html[data-nav="mini"]')
            pg.wait_for_timeout(400)
            shot(pg, "03a-collapsed.png")
            pg.click('.launch .hist-toggle')
            pg.click('[data-action="app.nav"]')
            pg.wait_for_selector('.entry[data-collapsed="false"]')
            pg.hover('.hrow:has-text("咏雪")')
            pg.click('.hrow:has-text("咏雪") [data-action="entry.renaming"]')
            pg.fill(".hrow__rename", "咏雪 · 期中卷")
            pg.press(".hrow__rename", "Enter")
            pg.wait_for_selector('.hrow:has-text("咏雪 · 期中卷")')
            pg.hover('.hrow:has-text("期中卷")')
            pg.click('.hrow:has-text("期中卷") [data-action="entry.trash"]')
            pg.click('dialog.dlg button[value="yes"]')
            pg.wait_for_function("!document.querySelector('.hist__list').innerText.includes('期中卷')")
            pg.click('[data-action="entry.view"][data-arg="trash"]')
            pg.wait_for_selector('.hrow:has-text("期中卷")')
            pg.click('.hrow:has-text("期中卷") [data-action="entry.undiscard"]')
            pg.wait_for_function("!document.querySelector('.hist__list').innerText.includes('期中卷')")
            pg.click('[data-action="entry.view"][data-arg="all"]')
            pg.wait_for_selector('.hrow:has-text("期中卷")')
            shot(pg, "03b-history.png")

            pg.goto(base + "/#/library")
            pg.wait_for_selector(".row")
            assert pg.locator(".row").count() == 8, pg.locator(".row").count()
            pg.click('.row:has-text("静夜思")')
            pg.wait_for_selector(".lib__detail")
            assert "2 次录入" in pg.inner_text(".lib__stats")
            pg.select_option('.rec__add select[name="grade"]', "1")
            pg.click('.rec__add button')
            pg.wait_for_selector(".rec")
            old_id = pg.get_attribute('.rec [data-action="lib.void"]', "data-arg")
            pg.select_option(".rec__grade", "3")             # 改评会换成新的记录编号：等页面换上新编号再撤销
            pg.wait_for_function("old => { const b = document.querySelector('.rec [data-action=\"lib.void\"]'); return b && b.dataset.arg !== old; }",
                                 arg=old_id)
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
            pg.click('[data-action="lib.facet"][data-arg="status:deleted"]')          # 分面筛选：已删除
            pg.wait_for_function("document.querySelectorAll('.row').length === 1")
            pg.click(".row")
            pg.click('[data-action="lib.restore"]')
            pg.wait_for_selector('[data-action="lib.delete"]')
            pg.click('[data-action="lib.facet"][data-arg="status:deleted"]')          # 再点一次取消
            pg.wait_for_function("document.querySelectorAll('.row').length === 8")
            pg.click('[data-action="lib.facet"][data-arg="kind:recall"]')             # 记忆型 = 3 道默写
            pg.wait_for_function("document.querySelectorAll('.row').length === 3")
            pg.click('[data-action="lib.clear"]')
            pg.wait_for_function("document.querySelectorAll('.row').length === 8")
            pg.click('[data-action="lib.group"][data-arg="material"]')                # 按篇：两篇阅读 + 两个默写出处
            pg.wait_for_function("document.querySelectorAll('.grpc').length === 4")
            pg.click('[data-action="lib.selecting"]')
            pg.click('.grpc:has-text("春望") [data-action="lib.pickGroup"]')
            pg.wait_for_selector('.lib__batch b:has-text("已选 2 题")')
            shot(pg, "04b-library-groups.png")
            pg.click('[data-action="lib.batchReview"]')                              # 批量加入复习 → 复习页的自选题

            plan_ready = lambda: pg.wait_for_function("document.querySelector('.pl__row') && !document.querySelector('.pl__list.is-busy')")  # noqa: E731
            pg.wait_for_selector('.pl__row .chip--ok')
            plan_ready()
            assert pg.locator('.pl__row .chip--ok:has-text("自选")').count() == 2
            pg.click('[data-action="rv.budget"][data-arg="20"]')
            plan_ready()
            first = pg.get_attribute('.pl__row:has([data-action="rv.exclude"]) >> nth=0', "data-key")
            pg.click(f'.pl__row[data-key="{first}"] [data-action="rv.exclude"]')        # 移除 → 别的题补位
            pg.wait_for_function("id => !document.querySelector(`.pl__row[data-key='${id}']`) && document.querySelector('.pl__sum').innerText.includes('移除了 1 道')", arg=first)
            pg.click('[data-action="rv.unexclude"]')
            pg.wait_for_selector(f'.pl__row[data-key="{first}"]')
            plan_ready()
            pg.click('.pk__row [data-action="rv.pin"] >> nth=0')                      # 从题库挑一道
            pg.wait_for_function("document.querySelectorAll('.pl__row .chip--ok').length === 3")
            pg.click('[data-action="rv.budget"][data-arg="60"]')
            pg.wait_for_function("document.querySelectorAll('.pl__row').length >= 7")
            plan_ready()
            planned = pg.locator(".pl__row").count()
            pinned_jys = pg.locator('.pl__group:has-text("默写") .pl__row:has(.chip--ok):has-text("床前明月光")').count()
            assert planned == 7 + pinned_jys, planned                               # 静夜思今天刚补记过：提前复习时跳过（除非是自选）
            shot(pg, "05a-plan.png", full_page=True)
            pg.click('[data-action="rv.create"]')
            pg.wait_for_selector(".rv-q")                                           # 评分：一次一道题，左边答题卡
            assert pg.get_attribute(".rv-nav__row >> nth=0", "aria-current") == "step"
            pg.click('[data-action="rv.reveal"]')
            pg.click('.rv-score [data-grade="2"]')
            pg.wait_for_selector('.rv-score__opt[aria-pressed="true"][data-grade="2"]')
            pg.wait_for_selector('.rv-nav__row[data-grade="2"]')                     # 答题卡同步着色
            pg.fill(".rv-fb__input", "漏了第二个采分点")
            pg.keyboard.press("Enter")                                              # 回车保存反馈
            pg.wait_for_selector('.toast:has-text("反馈已保存")')
            shot(pg, "05-grading.png")
            href = pg.get_attribute('.rv-top a[href^="/print/session"]', "href")
            pr = ctx.new_page()
            pr.goto(base + href + "&answers=1")
            assert pr.locator(".lines div").count() > 20 and pr.locator(".blank").count() >= 2
            shot(pr, "06-print.png", full_page=True)

            target = "document.querySelector('.ai__target')?.innerText.includes('第 {} 题')"
            pg.click(".rv-q__stem")                                                 # 焦点离开输入框，键盘换题
            pg.keyboard.press("ArrowRight")
            pg.wait_for_function(target.format(2))                                  # 复习助手跟着换到第 2 题
            pg.keyboard.press("ArrowLeft")
            pg.wait_for_function(target.format(1))
            assert pg.input_value(".rv-fb__input") == "漏了第二个采分点"               # 反馈确实存下了
            pg.keyboard.press("ArrowRight")
            pg.wait_for_function(target.format(2))
            pg.fill("#ai-composer", "这题从哪几方面想？")
            pg.keyboard.press("Enter")
            pg.wait_for_selector('.ai__msg--bot[data-status="done"]', timeout=20000)
            bot = ".ai__msg--bot >> nth=0"
            assert "作用" in pg.inner_text(bot)
            assert pg.locator(f"{bot} >> .ai-think").count() >= 1                  # 思考过程看得见
            done_tools = pg.locator(f'{bot} >> .ai-tool[data-status="done"]')       # 按需查阅：先看题，再读原文
            assert done_tools.count() >= 1 and "看第 2 题" in done_tools.nth(0).inner_text(), done_tools.count()
            done_tools.nth(0).locator(".ai-tool__head").click()
            pg.wait_for_selector('.ai-tool__out:has-text("参考答案")')               # 展开看查到的内容
            assert pg.input_value("#ai-composer") == ""
            pg.evaluate("""() => { const r = document.createRange(); r.selectNodeContents(document.querySelector('.rv-q__stem'));
              const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); }""")   # 选中题干 → 引用
            pg.click(".rv-quote")
            pg.wait_for_selector('.ai-ref:has-text("第 2 题题干")')
            fake_ai.REQUESTS.clear()
            pg.fill("#ai-composer", "这句怎么理解？")
            pg.keyboard.press("Enter")
            pg.wait_for_selector('.ai__msg--bot[data-status="done"] >> nth=1', timeout=20000)
            assert pg.locator(".ai__msg--user >> nth=1 >> .ai-quote").count() == 1
            assert pg.locator(".ai-ref").count() == 0                               # 发出后输入框里的引用清空
            assert "（引用 1：第 2 题的题干）" in json.dumps(fake_ai.REQUESTS[0], ensure_ascii=False)
            pg.fill("#ai-composer", "我的作答：灯是线索，贯穿全文。")
            pg.click('[data-action="rv.aiMode"][data-arg="grade"]')                   # 输入框里的作答 + 打分
            pg.wait_for_selector(".ai-sug", timeout=20000)
            assert "基本" in pg.inner_text(".ai-sug")
            pg.click('[data-action="rv.aiAdopt"][data-arg$=":all"]')
            pg.wait_for_selector('.rv-score__opt[aria-pressed="true"][data-grade="2"]')
            pg.wait_for_function("document.querySelector('.rv-fb__input')?.value.includes('漏了象征义')")
            pg.click(".rv-nav__row >> nth=2")                                       # 答题卡点第 3 题
            pg.wait_for_function(target.format(3))
            pg.click('[data-action="rv.aiMode"][data-arg="feedback"]')               # 写反馈：还没评分 → 先暂存
            pg.wait_for_selector('.ai__msg--bot[data-status="done"] .ai-sug', timeout=20000)
            pg.click('[data-action="rv.aiAdopt"][data-arg$=":note"]')
            pg.wait_for_selector(".rv-fb.is-pending")
            pg.keyboard.press("3")                                                  # 键盘自评，暂存的反馈一起写入
            pg.wait_for_selector('.rv-score__opt[aria-pressed="true"][data-grade="3"]')
            pg.wait_for_selector(".rv-fb:not(.is-pending)")
            assert "作用题" in pg.input_value(".rv-fb__input")
            shot(pg, "06b-assistant.png")
            pg.click(".rv-nav__row >> nth=0")                                       # 改评分：原来的反馈保留
            pg.wait_for_function(target.format(1))
            pg.keyboard.press("3")
            pg.wait_for_selector('.rv-score__opt[aria-pressed="true"][data-grade="3"]')
            assert pg.input_value(".rv-fb__input") == "漏了第二个采分点"
            pg.click('[data-action="rv.back"]')
            pg.wait_for_selector(".rv-sess")                                        # 左栏复习记录
            assert f"评了 3/{planned}" in pg.inner_text(".rv-sess >> nth=0"), pg.inner_text(".rv-sess >> nth=0")

            pg.goto(base + "/#/library")                                               # 复习记录分页
            pg.click('[data-action="lib.tab"][data-arg="history"]')
            pg.wait_for_selector(".hst__row")
            assert pg.locator(".hst__row").count() == 4, pg.locator(".hst__row").count()  # 补记 1 + 本次 3
            pg.check('input[data-arg="note"]')
            pg.wait_for_function("document.querySelectorAll('.hst__row').length === 3")
            pg.click(".hst__row >> nth=0")
            pg.wait_for_selector(".lib__detail")
            shot(pg, "06c-history.png")
            pg.uncheck('input[data-arg="note"]')
            pg.click('[data-action="lib.tab"][data-arg="items"]')

            pg.goto(base + "/#/entry")
            pg.click('.hist [data-action="entry.fresh"]')
            pg.wait_for_function("document.querySelector('.launch:not(:has(.launch__pages))') && document.activeElement?.id === 'composer'")
            pg.fill("#composer", "停用 Q-000003")
            pg.keyboard.press("Enter")
            pg.wait_for_selector('.chat__title:has-text("停用 Q-000003")', timeout=30000)   # 确认看的是这段新对话
            pg.wait_for_selector('.blk--tool[data-tool="library_suspend"][data-status="done"]', timeout=30000)
            pg.wait_for_selector('.blk--run[data-status="done"]', timeout=30000)
            pg.click('.blk--tool[data-tool="library_suspend"] > .blk__head')
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
            mp.wait_for_selector(".chat__head, .launch")
            mp.click(".hist-toggle")
            mp.wait_for_selector('.entry[data-hist="open"] .hrow')
            shot(mp, "08a-mobile-history.png")
            mp.click('.hrow:has-text("期中卷") .hrow__main')
            mp.wait_for_selector(".tl .blk--tool")                      # 窄屏打开草稿先看对话（执行过程）
            mp.click('[data-action="entry.tab"][data-arg="draft"]')
            mp.wait_for_selector(".canvas")
            assert mp.evaluate("document.documentElement.scrollWidth") <= 390
            shot(mp, "08-mobile-draft.png")
            mp.click('[data-action="entry.tab"][data-arg="chat"]')
            shot(mp, "09-mobile-chat.png")
            mp.goto(base + "/#/review")                          # 窄屏复习：左栏是抽屉、助手是底部面板，不横向溢出
            mp.click(".rv-top__rail")
            mp.wait_for_selector('.rv[data-rail="open"] .rv-sess')
            mp.click(".rv-sess >> nth=0 >> .rv-sess__main")
            mp.wait_for_selector(".rv-q")
            assert mp.evaluate("document.documentElement.scrollWidth") <= 390
            mp.click(".rv-top__ai")
            mp.wait_for_selector('.rv[data-ai="open"] #ai-composer')
            shot(mp, "09b-mobile-review.png")
            from e2e_pdf import check_pdf
            check_pdf(browser, base, vault, images, shots)
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
